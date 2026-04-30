# MaUWB ESP32S3 UWB 모듈 테스트 세팅 기록

## 개요

- 모듈: MaUWB_ESP32S3 (DW3000) × 5개
- 목적: UWB 거리 측정(Ranging) 및 위치 추적(Positioning) 테스트
- 참고 레포: https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command

---

## 1. Arduino IDE 환경 설정

### 1-1. ESP32S3 보드 추가

Arduino IDE → 설정(Preferences) → "Additional Board Manager URLs"에 아래 URL 추가:

```
https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```

보드 매니저(Board Manager)에서 `esp32` 검색 → **esp32 by Espressif Systems** 설치.

### 1-2. 라이브러리 설치

라이브러리 매니저에서 `Adafruit SSD1306` 검색 후 Install → **Install All** 선택 시 의존 라이브러리(Adafruit GFX Library, Adafruit BusIO)가 자동으로 함께 설치됨.

### 1-3. 보드 설정

- Board: **ESP32S3 Dev Module**
- USB CDC On Boot: **Enabled**
- Upload Speed: **921600**

---

## 2. USB 드라이버 설치

모듈을 PC에 USB-C로 연결했을 때 COM 포트가 잡히지 않는 경우, CH343 시리얼 드라이버 설치가 필요함.

- 다운로드: https://www.wch.cn/downloads/CH343SER_EXE.html
- `CH343SER.EXE` 실행 → INSTALL 클릭
- 설치 후 USB 재연결 시 장치관리자 "포트(COM & LPT)"에 COM 포트가 잡히는 것을 확인

---

## 3. 모듈 USB 포트 구분

모듈에 USB-C 포트가 2개 있음:

| 포트 | 용도 |
| --- | --- |
| **USB-NATIVE** | 시리얼 모니터 출력 (데이터 확인용) |
| **USB-TTL** | 펌웨어 업로드용 (Arduino IDE에서 Upload 시 사용) |
- 펌웨어 업로드: **USB-TTL** 에 연결
- 시리얼 모니터로 데이터 확인: **USB-NATIVE** 에 연결

---

## 4. 펌웨어 업로드

### 4-1. Anchor 펌웨어

`esp32s3_anchor.ino`를 사용하며, 각 모듈마다 `UWB_INDEX` 값만 변경하여 업로드.

```c
#define UWB_INDEX 0   // Anchor ID: 0, 1, 2, 3 중 하나
#define PAN_INDEX 0
#define ANCHOR
#define UWB_TAG_COUNT 1
```

| 모듈 | UWB_INDEX | OLED 표시 |
| --- | --- | --- |
| Anchor 0 | 0 | A0  6.8M |
| Anchor 1 | 1 | A1  6.8M |
| Anchor 2 | 2 | A2  6.8M |

업로드 절차:

1. USB-TTL에 케이블 연결
2. Arduino IDE → Tools → Port에서 COM 포트 선택
3. Upload 클릭
4. OLED에 해당 Anchor ID가 표시되면 성공

### 4-2. Tag 펌웨어

**거리 측정 테스트용:** `esp32s3_tag.ino` 사용

```c
#define UWB_INDEX 0
#define PAN_INDEX 0
#define TAG
#define UWB_TAG_COUNT 1
```

**위치 추적용:** `esp32s3_get_range.ino` 사용 — AT+RANGE 데이터를 파싱하여 JSON 형태로 시리얼 출력.

---

## 5. 거리 측정 테스트 (Ranging)

### 구성

Anchor 1개 + Tag 1개

### 절차

1. Anchor 모듈: 전원 연결 (USB 또는 배터리)
2. Tag 모듈: USB-NATIVE로 PC에 연결
3. Arduino IDE → Serial Monitor 열기 (baud rate: 115200)
4. 시리얼 모니터에서 거리 데이터 확인

### 출력 형식

```
AT+RANGE=tid:0,mask:01,seq:71,range:(42,0,0,0,0,0,0,0),ancid:(0,-1,-1,-1,-1,-1,-1,-1)
```

### 데이터 읽는 법

| 필드 | 의미 |
| --- | --- |
| `tid:0` | Tag ID 0번 |
| `mask:01` | 연결된 Anchor 비트마스크 |
| `seq:71` | 측정 순서 번호 |
| `range:(42,0,0,0,0,0,0,0)` | 각 Anchor까지의 거리(cm). 첫 번째 값 42 = A0까지 42cm |
| `ancid:(0,-1,-1,-1,-1,-1,-1,-1)` | 연결된 Anchor ID. -1 = 미연결 |

### 테스트 결과

- 모듈을 붙여놨을 때: 약 37~42cm (UWB 특성상 근거리 오차 존재)
- 1m 거리: 약 200cm (안테나 딜레이 캘리브레이션 미적용 상태)
- 거리 변화에 따라 값이 비례하여 변동하는 것을 확인 → **정상 동작**

---

## 6. 위치 추적 테스트 (Positioning) — 진행 중

### 구성

Anchor 3개 (A0, A1, A2) + Tag 1개 (get_range 펌웨어)

### get_range 출력 형식

```json
{"id":0,"range":[120,95,143,0,0,0,0,0]}
```

→ A0까지 120cm, A1까지 95cm, A2까지 143cm

### 다음 단계

1. Anchor 3개 삼각형 배치 및 좌표 설정
2. Python(position.py)으로 Tag 위치 실시간 시각화
3. 필요 시 Anchor 1개 추가(A3)하여 4개 구성으로 확장

---

## 참고

- MaUWB 스펙: Anchor 최대 8개(ID 0~7), Tag 최대 64개(ID 0~63)
- DW3000 기반, 최대 500m 범위, 정밀도 약 0.5m (100m 이내)
- 모듈 구분을 위해 네임 스티커(A0, A1, A2, T0) 부착 권장
- 버튼: RST(리셋), FLASH(다운로드 모드 진입 — FLASH 누른 채 RST 눌렀다 떼기)  

<video controls src="assets/test.mp4" title="Title"></video>