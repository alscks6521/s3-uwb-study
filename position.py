import pygame
import socket
import json
import math
import sys
import threading
import time

try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("[경고] pyttsx3 라이브러리가 없습니다. 음성 안내를 사용하려면 'pip install pyttsx3'를 실행하세요.")

# ============================================================
# 1. 환경 설정
# ============================================================
UDP_PORT = 12345

# 앵커 좌표 설정 (단위: cm)
# A1이 위(0,0), A0가 아래(0,-185)에 오도록 설정
ANCHORS = {
    0: (0, -185),       # A0: A1에서 수직 아래로 185cm
    1: (0, 0),          # A1: 기준점 (화면상 위쪽)
    2: (-178, -93),     # A2: 두 앵커의 왼쪽 지점
}

# 알고리즘 파라미터
MEDIAN_WINDOW = 5    # 중간값 필터 윈도우 크기
ALPHA = 0.2          # EMA 스무딩 계수 (낮을수록 부드럽지만 느림)
JUMP_LIMIT = 200     # 이상치 제거 (cm)
MOVE_THRESHOLD = 15  # 이동 판단 최소 거리 (cm)

# 화면 및 색상
WINDOW_W, WINDOW_H = 1000, 750
MARGIN = 100
BG_COLOR = (25, 25, 30)
GRID_COLOR = (45, 45, 50)
ANCHOR_COLOR = (0, 180, 255)
TAG_COLOR = (255, 60, 60)
DEST_COLOR = (60, 255, 100)
TEXT_COLOR = (220, 220, 220)
ARROW_COLOR = (255, 200, 50)
GUIDE_BG = (40, 40, 50)

# 전역 상태 변수
DESTINATION = None
tags_data = {}
lock = threading.Lock()
distance_buffers = {}

# ============================================================
# 2. 계산 및 알고리즘 함수
# ============================================================

def trilateration(anchors, distances):
    """삼변측량 알고리즘"""
    valid = [(aid, anchors[aid], d) for aid, d in distances.items() if aid in anchors and d > 0]
    if len(valid) < 3: return None
    _, (x0, y0), r0 = valid[0]
    _, (x1, y1), r1 = valid[1]
    _, (x2, y2), r2 = valid[2]
    A = 2 * (x1 - x0); B = 2 * (y1 - y0)
    C = r0**2 - r1**2 - x0**2 + x1**2 - y0**2 + y1**2
    D = 2 * (x2 - x0); E = 2 * (y2 - y0)
    F = r0**2 - r2**2 - x0**2 + x2**2 - y0**2 + y2**2
    denom = A * E - B * D
    if abs(denom) < 0.001: return None
    x = (C * E - F * B) / denom
    y = (A * F - D * C) / denom
    return (x, y)

def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0: return 0
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2

def filter_distances(tag_id, raw_distances):
    """거리값 필터링"""
    if tag_id not in distance_buffers: distance_buffers[tag_id] = {}
    filtered = {}
    for aid, dist in raw_distances.items():
        if aid not in distance_buffers[tag_id]: distance_buffers[tag_id][aid] = []
        buf = distance_buffers[tag_id][aid]
        buf.append(dist)
        if len(buf) > MEDIAN_WINDOW: buf.pop(0)
        filtered[aid] = median(buf)
    return filtered

def get_heading(history):
    """이동 방향 추정"""
    if len(history) < 3: return None
    n = min(5, len(history) - 1)
    dx = sum(history[i][0] - history[i-1][0] for i in range(-n, 0)) / n
    dy = sum(history[i][1] - history[i-1][1] for i in range(-n, 0)) / n
    if math.sqrt(dx**2 + dy**2) < 5: return None
    return math.atan2(-dy, dx)

def get_direction_guide(heading, tag_pos, dest):
    """음성 및 텍스트 안내 생성"""
    dx, dy = dest[0] - tag_pos[0], dest[1] - tag_pos[1]
    dist = math.sqrt(dx**2 + dy**2)
    if dist < 50: return "도착했습니다!", dist, 0
    target_angle = math.atan2(-dy, dx)
    if heading is None: return "위치 파악을 위해 조금 더 걸어주세요", dist, 0
    diff = target_angle - heading
    while diff > math.pi: diff -= 2 * math.pi
    while diff < -math.pi: diff += 2 * math.pi
    diff_deg = math.degrees(diff)
    dist_m = dist / 100
    if abs(diff_deg) < 20: guide = f"직진 {dist_m:.1f}미터"
    elif abs(diff_deg) < 60: guide = f"살짝 {'왼쪽' if diff_deg > 0 else '오른쪽'} {dist_m:.1f}미터"
    elif abs(diff_deg) < 120: guide = f"{'왼쪽' if diff_deg > 0 else '오른쪽'}으로 {dist_m:.1f}미터"
    else: guide = f"뒤로 돌아서 {dist_m:.1f}미터"
    return guide, dist, diff_deg

# ============================================================
# 3. 보조 클래스 (TTS, UDP, 좌표변환)
# ============================================================

class VoiceGuide:
    def __init__(self):
        self.last_guide, self.last_speak_time = "", 0
        self.engine, self.queue, self.lock = None, [], threading.Lock()
        if TTS_AVAILABLE:
            try:
                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", 180)
                voices = self.engine.getProperty("voices")
                for v in voices:
                    if "korean" in v.name.lower() or "ko" in v.id.lower():
                        self.engine.setProperty("voice", v.id); break
                threading.Thread(target=self._run, daemon=True).start()
            except: self.engine = None

    def _run(self):
        while True:
            text = None
            with self.lock:
                if self.queue: text = self.queue.pop(0)
            if text: self.engine.say(text); self.engine.runAndWait()
            time.sleep(0.1)

    def speak(self, text):
        now = time.time()
        interval = 3 if text == self.last_guide else 1.5
        if now - self.last_speak_time > interval:
            self.last_guide, self.last_speak_time = text, now
            with self.lock: self.queue.clear(); self.queue.append(text)

def make_converter(anchors):
    all_p = list(anchors.values())
    min_x, max_x = min(p[0] for p in all_p)-200, max(p[0] for p in all_p)+200
    min_y, max_y = min(p[1] for p in all_p)-200, max(p[1] for p in all_p)+200
    scale = min((WINDOW_W-2*MARGIN)/(max_x-min_x), (WINDOW_H-2*MARGIN)/(max_y-min_y))
    def to_s(p): return (int(MARGIN+(p[0]-min_x)*scale), int(MARGIN+(p[1]-min_y)*scale))
    def from_s(p): return ((p[0]-MARGIN)/scale+min_x, (p[1]-MARGIN)/scale+min_y)
    return to_s, from_s

def udp_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("192.168.0.51", 12345))
    sock.settimeout(1.0)
    print(f"[UDP] 서버 가동 중 (포트: {UDP_PORT})")
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            line = data.decode("utf-8", errors="ignore").strip()
            if "AT+RANGE" in line and "range:(" in line:
                try:
                    tag_id = int(line.split("tid:")[1].split(",")[0])
                    range_part = line.split("range:(")[1].split(")")[0]
                    raw_distances = {i: float(v) for i, v in enumerate(range_part.split(",")) if float(v) > 0 and i in ANCHORS}
                    if len(raw_distances) >= 3:
                        dist = filter_distances(tag_id, raw_distances)
                        raw_pos = trilateration(ANCHORS, dist)
                        with lock:
                            if tag_id not in tags_data: tags_data[tag_id] = {"pos": None, "history": [], "distances": {}, "heading": None}
                            tags_data[tag_id]["distances"] = raw_distances
                            if raw_pos:
                                prev = tags_data[tag_id]["pos"]
                                if not prev or math.sqrt((raw_pos[0]-prev[0])**2+(raw_pos[1]-prev[1])**2) < JUMP_LIMIT:
                                    pos = (prev[0]+ALPHA*(raw_pos[0]-prev[0]), prev[1]+ALPHA*(raw_pos[1]-prev[1])) if prev else raw_pos
                                    tags_data[tag_id]["pos"] = pos
                                    hist = tags_data[tag_id]["history"]
                                    if not hist or math.sqrt((pos[0]-hist[-1][0])**2+(pos[1]-hist[-1][1])**2) > MOVE_THRESHOLD:
                                        hist.append(pos); 
                                        if len(hist) > 50: hist.pop(0)
                                    tags_data[tag_id]["heading"] = get_heading(hist)
                except: pass
        except: continue

# ============================================================
# 4. 메인 실행 루프
# ============================================================

def main():
    global DESTINATION
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("UWB 시각장애인 안내 프로토타입")
    clock, voice = pygame.time.Clock(), VoiceGuide()
    threading.Thread(target=udp_receiver, daemon=True).start()

    f_big = pygame.font.SysFont("malgun gothic", 22, bold=True)
    f_mid = pygame.font.SysFont("malgun gothic", 18)
    f_guide = pygame.font.SysFont("malgun gothic", 32, bold=True)
    to_screen, from_screen = make_converter(ANCHORS)

    running, cur_guide = True, "화면을 클릭하여 목적지를 설정하세요"
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.MOUSEBUTTONDOWN:
                DESTINATION = from_screen(event.pos)
                voice.speak("목적지가 설정되었습니다.")
            if event.type == pygame.KEYDOWN and event.key == pygame.K_r: DESTINATION = None

        screen.fill(BG_COLOR)
        for i in range(0, 1000, 50): pygame.draw.line(screen, GRID_COLOR, (i, 0), (i, 750))
        for i in range(0, 750, 50): pygame.draw.line(screen, GRID_COLOR, (0, i), (1000, i))

        # 앵커 그리기
        for aid, apos in ANCHORS.items():
            sp = to_screen(apos)
            pygame.draw.circle(screen, ANCHOR_COLOR, sp, 10)
            screen.blit(f_big.render(f"A{aid}", True, ANCHOR_COLOR), (sp[0]-10, sp[1]-30))

        # 목적지 그리기
        if DESTINATION:
            dp = to_screen(DESTINATION)
            pygame.draw.circle(screen, DEST_COLOR, dp, 12, 2)
            screen.blit(f_big.render("목적지", True, DEST_COLOR), (dp[0]-20, dp[1]-30))

        # 태그 그리기 및 안내
        with lock:
            for tid, tdata in tags_data.items():
                if tdata["pos"]:
                    sp = to_screen(tdata["pos"])
                    pygame.draw.circle(screen, TAG_COLOR, sp, 12)
                    if tdata["heading"] is not None:
                        ex = sp[0] + 40 * math.cos(tdata["heading"])
                        ey = sp[1] - 40 * math.sin(tdata["heading"])
                        pygame.draw.line(screen, ARROW_COLOR, sp, (int(ex), int(ey)), 3)
                    
                    if DESTINATION:
                        g_txt, d, _ = get_direction_guide(tdata["heading"], tdata["pos"], DESTINATION)
                        cur_guide = g_txt
                        voice.speak(g_txt)

        # 하단 패널
        pygame.draw.rect(screen, GUIDE_BG, (0, 670, 1000, 80))
        txt_surf = f_guide.render(cur_guide, True, DEST_COLOR if "도착" in cur_guide else TEXT_COLOR)
        screen.blit(txt_surf, (500 - txt_surf.get_width()//2, 685))
        
        pygame.display.flip()
        clock.tick(30)
    pygame.quit()

if __name__ == "__main__":
    main()