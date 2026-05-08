"""
UWB 실내 지도 실시간 시각화 스크립트
- UDP로 T0 태그 데이터를 수신
- 삼각측량(Trilateration)으로 (x, y) 좌표 계산
- matplotlib로 사무실 지도 + 실시간 위치 표시

사용법: python uwb_map.py
"""

import socket
import threading
import re
import math
import json
import time
import sys

# ============================================================
# 설정값 (본인 환경에 맞게 수정)
# ============================================================

UDP_PORT = 12345

# 앵커 좌표 (2D, 미터) - 높이 보정 완료된 값
#
#  A1(0, 14.8) -------- A2(9.4, 14.8)
#  |                           |
#  |        사무실              |
#  |      9.4m × 14.8m         |
#  |                           |
#  A0(0, 0)   ---------- A3(9.4, 0)

ANCHORS = {
    0: {"x": 0.0,  "y": 0.0,   "name": "A0", "height": 2.5},
    1: {"x": 0.0,  "y": 14.8,  "name": "A1", "height": 2.5},
    2: {"x": 9.4,  "y": 14.8,  "name": "A2", "height": 2.5},
    3: {"x": 9.4,  "y": 0.0,   "name": "A3", "height": 2.5},
}

TAG_HEIGHT = 0.85  # T0 들고 있는 높이 (미터)

OFFICE_WIDTH = 9.4    # 가로 (m)
OFFICE_LENGTH = 14.8  # 세로 (m)

# 노드 (나중에 추가) - 갈림길, 문, 주요 지점
NODES = [
    # {"id": "entrance", "x": 4.7, "y": 0.5, "name": "출입구"},
    # {"id": "meeting_room", "x": 8.0, "y": 10.0, "name": "회의실"},
]

# ============================================================
# 삼각측량 함수
# ============================================================

def convert_3d_to_2d(distance_3d_cm, anchor_height, tag_height):
    """3D 거리(cm)에서 높이 성분을 제거하여 2D 수평 거리(m)를 반환"""
    d3d = distance_3d_cm / 100.0  # cm → m
    height_diff = anchor_height - tag_height
    d2d_sq = d3d**2 - height_diff**2
    if d2d_sq > 0:
        return math.sqrt(d2d_sq)
    return d3d  # 높이보정 불가능하면 원본 사용


def trilaterate(distances):
    """
    최소 3개 앵커의 거리로 (x, y) 좌표 계산
    Least Squares 방식
    distances: {anchor_id: distance_2d_meters, ...}
    """
    valid = {k: v for k, v in distances.items() if k in ANCHORS and v > 0}
    
    if len(valid) < 3:
        return None, None
    
    # 앵커 목록
    anchor_ids = list(valid.keys())
    
    # 기준 앵커 (첫 번째)
    ref_id = anchor_ids[0]
    ref_x = ANCHORS[ref_id]["x"]
    ref_y = ANCHORS[ref_id]["y"]
    ref_d = valid[ref_id]
    
    # Ax = b 형태로 선형화 (최소제곱법)
    A = []
    b = []
    
    for i in range(1, len(anchor_ids)):
        aid = anchor_ids[i]
        ax = ANCHORS[aid]["x"]
        ay = ANCHORS[aid]["y"]
        d = valid[aid]
        
        # 선형화: 2*(ax - ref_x)*x + 2*(ay - ref_y)*y = (ref_d^2 - d^2) + (ax^2 - ref_x^2) + (ay^2 - ref_y^2)
        A.append([2 * (ax - ref_x), 2 * (ay - ref_y)])
        b.append(
            (ref_d**2 - d**2)
            + (ax**2 - ref_x**2)
            + (ay**2 - ref_y**2)
        )
    
    # 최소제곱법 풀기 (A^T A x = A^T b)
    try:
        # 2x2 이상 행렬
        n = len(A)
        if n < 2:
            return None, None
        
        # A^T * A
        ata00 = sum(A[i][0] * A[i][0] for i in range(n))
        ata01 = sum(A[i][0] * A[i][1] for i in range(n))
        ata10 = ata01
        ata11 = sum(A[i][1] * A[i][1] for i in range(n))
        
        # A^T * b
        atb0 = sum(A[i][0] * b[i] for i in range(n))
        atb1 = sum(A[i][1] * b[i] for i in range(n))
        
        # 역행렬
        det = ata00 * ata11 - ata01 * ata10
        if abs(det) < 1e-10:
            return None, None
        
        x = (ata11 * atb0 - ata01 * atb1) / det
        y = (ata00 * atb1 - ata10 * atb0) / det
        
        # 사무실 범위 밖이면 클램핑
        x = max(-1.0, min(OFFICE_WIDTH + 1.0, x))
        y = max(-1.0, min(OFFICE_LENGTH + 1.0, y))
        
        return round(x, 2), round(y, 2)
        
    except Exception as e:
        print(f"삼각측량 오류: {e}")
        return None, None


# ============================================================
# UDP 데이터 파싱
# ============================================================

def parse_range_data(line):
    """
    AT+RANGE 데이터를 파싱하여 앵커별 거리(cm) 반환
    입력 예: AT+RANGE=tid:7,mask:0F,seq:128,range:(997,1321,911,738,0,0,0,0),ancid:(0,1,2,3,-1,-1,-1,-1)
    """
    try:
        range_match = re.search(r'range:\(([^)]+)\)', line)
        ancid_match = re.search(r'ancid:\(([^)]+)\)', line)
        
        if not range_match or not ancid_match:
            return None
        
        ranges = [int(x) for x in range_match.group(1).split(',')]
        ancids = [int(x) for x in ancid_match.group(1).split(',')]
        
        result = {}
        for i, aid in enumerate(ancids):
            if aid >= 0 and i < len(ranges) and ranges[i] > 0:
                result[aid] = ranges[i]
        
        return result
        
    except Exception as e:
        print(f"파싱 오류: {e}")
        return None


# ============================================================
# 메인: 콘솔 모드 (matplotlib 없이도 동작)
# ============================================================

def run_console_mode():
    """matplotlib 없이 콘솔에서 좌표를 출력"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', UDP_PORT))
    sock.settimeout(1.0)
    
    print(f"\n{'='*60}")
    print(f"  UWB 실내 위치 추적 시스템")
    print(f"  사무실: {OFFICE_WIDTH}m × {OFFICE_LENGTH}m")
    print(f"  UDP 포트 {UDP_PORT} 수신 대기중...")
    print(f"{'='*60}\n")
    print(f"  앵커 좌표:")
    for aid, info in ANCHORS.items():
        print(f"    {info['name']}: ({info['x']}, {info['y']})")
    print()
    
    # 이동 평균 필터
    history_x = []
    history_y = []
    FILTER_SIZE = 5
    
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            line = data.decode('utf-8', errors='ignore').strip()
            
            raw_distances = parse_range_data(line)
            if not raw_distances:
                continue
            
            # 3D → 2D 변환
            distances_2d = {}
            dist_str_parts = []
            for aid, d3d_cm in raw_distances.items():
                if aid in ANCHORS:
                    d2d = convert_3d_to_2d(d3d_cm, ANCHORS[aid]["height"], TAG_HEIGHT)
                    distances_2d[aid] = d2d
                    dist_str_parts.append(f"A{aid}:{d2d:.2f}m")
            
            # 삼각측량
            x, y = trilaterate(distances_2d)
            
            if x is not None and y is not None:
                # 이동 평균 필터
                history_x.append(x)
                history_y.append(y)
                if len(history_x) > FILTER_SIZE:
                    history_x.pop(0)
                    history_y.pop(0)
                
                avg_x = sum(history_x) / len(history_x)
                avg_y = sum(history_y) / len(history_y)
                
                # 가장 가까운 노드 찾기
                nearest_node = ""
                if NODES:
                    min_dist = float('inf')
                    for node in NODES:
                        nd = math.sqrt((avg_x - node["x"])**2 + (avg_y - node["y"])**2)
                        if nd < min_dist:
                            min_dist = nd
                            nearest_node = f" | 가장 가까운 지점: {node['name']} ({min_dist:.1f}m)"
                
                print(f"  위치: ({avg_x:.2f}, {avg_y:.2f}) | {' | '.join(dist_str_parts)}{nearest_node}")
            
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("\n종료합니다.")
            break


# ============================================================
# 메인: matplotlib 실시간 시각화 모드
# ============================================================

def run_visual_mode():
    """matplotlib로 실시간 지도 시각화"""
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.animation import FuncAnimation
    
    # 공유 데이터
    current_pos = {"x": None, "y": None}
    trail = {"x": [], "y": []}
    MAX_TRAIL = 100
    
    # 이동 평균 필터
    history_x = []
    history_y = []
    FILTER_SIZE = 5
    
    # UDP 수신 스레드
    def udp_listener():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', UDP_PORT))
        sock.settimeout(1.0)
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                line = data.decode('utf-8', errors='ignore').strip()
                
                raw_distances = parse_range_data(line)
                if not raw_distances:
                    continue
                
                distances_2d = {}
                for aid, d3d_cm in raw_distances.items():
                    if aid in ANCHORS:
                        d2d = convert_3d_to_2d(d3d_cm, ANCHORS[aid]["height"], TAG_HEIGHT)
                        distances_2d[aid] = d2d
                
                x, y = trilaterate(distances_2d)
                
                if x is not None and y is not None:
                    history_x.append(x)
                    history_y.append(y)
                    if len(history_x) > FILTER_SIZE:
                        history_x.pop(0)
                        history_y.pop(0)
                    
                    current_pos["x"] = sum(history_x) / len(history_x)
                    current_pos["y"] = sum(history_y) / len(history_y)
                    
                    trail["x"].append(current_pos["x"])
                    trail["y"].append(current_pos["y"])
                    if len(trail["x"]) > MAX_TRAIL:
                        trail["x"].pop(0)
                        trail["y"].pop(0)
                        
            except socket.timeout:
                continue
            except Exception:
                continue
    
    listener_thread = threading.Thread(target=udp_listener, daemon=True)
    listener_thread.start()
    
    # ---- 시각화 ----
    fig, ax = plt.subplots(1, 1, figsize=(8, 12))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    
    # 사무실 영역
    office_rect = patches.Rectangle(
        (0, 0), OFFICE_WIDTH, OFFICE_LENGTH,
        linewidth=2, edgecolor='#e94560', facecolor='#0f3460', alpha=0.3
    )
    ax.add_patch(office_rect)
    
    # 앵커 표시
    for aid, info in ANCHORS.items():
        ax.plot(info["x"], info["y"], 's', color='#e94560', markersize=15, zorder=5)
        ax.annotate(
            info["name"], (info["x"], info["y"]),
            textcoords="offset points", xytext=(10, 10),
            fontsize=12, fontweight='bold', color='#e94560'
        )
    
    # 노드 표시
    for node in NODES:
        ax.plot(node["x"], node["y"], 'D', color='#f5c518', markersize=10, zorder=5)
        ax.annotate(
            node["name"], (node["x"], node["y"]),
            textcoords="offset points", xytext=(10, -15),
            fontsize=10, color='#f5c518'
        )
    
    # 태그 위치 (실시간 업데이트)
    tag_dot, = ax.plot([], [], 'o', color='#00ff41', markersize=18, zorder=10, alpha=0.9)
    trail_line, = ax.plot([], [], '-', color='#00ff41', linewidth=1.5, alpha=0.4, zorder=4)
    coord_text = ax.text(
        OFFICE_WIDTH / 2, OFFICE_LENGTH + 1.0, '',
        ha='center', va='bottom', fontsize=14, color='#00ff41',
        fontweight='bold', fontfamily='monospace'
    )
    
    # 축 설정
    ax.set_xlim(-1.5, OFFICE_WIDTH + 1.5)
    ax.set_ylim(-1.5, OFFICE_LENGTH + 2.0)
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.15, color='white')
    ax.set_xlabel('X (m)', color='white', fontsize=12)
    ax.set_ylabel('Y (m)', color='white', fontsize=12)
    ax.set_title('UWB 실내 위치 추적', color='white', fontsize=16, fontweight='bold', pad=20)
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#333')
    
    def update(frame):
        if current_pos["x"] is not None:
            tag_dot.set_data([current_pos["x"]], [current_pos["y"]])
            trail_line.set_data(trail["x"], trail["y"])
            coord_text.set_text(f'T0: ({current_pos["x"]:.2f}, {current_pos["y"]:.2f})')
        else:
            coord_text.set_text('T0: 수신 대기중...')
        return tag_dot, trail_line, coord_text
    
    ani = FuncAnimation(fig, update, interval=100, blit=True, cache_frame_data=False)
    
    print(f"\n  지도 시각화 시작! UDP 포트 {UDP_PORT} 수신중...")
    print(f"  창을 닫으면 종료됩니다.\n")
    
    plt.tight_layout()
    plt.show()


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    print("\n  모드 선택:")
    print("  1. 실시간 지도 시각화 (matplotlib 필요)")
    print("  2. 콘솔 모드 (좌표만 출력)")
    print()
    
    try:
        choice = input("  선택 (1 또는 2): ").strip()
    except EOFError:
        choice = "2"
    
    if choice == "1":
        try:
            import matplotlib
            run_visual_mode()
        except ImportError:
            print("\n  matplotlib가 없습니다. 설치 후 다시 시도하세요:")
            print("  pip install matplotlib")
            print("\n  콘솔 모드로 전환합니다...\n")
            run_console_mode()
    else:
        run_console_mode()