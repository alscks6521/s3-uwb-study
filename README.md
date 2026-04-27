## MaUWB_ESP32S3 UWB module

git 오픈소스 제공 : https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command

- 앵커 최대 8개 / 태그 최대 제한 64개
- ESP32-S3가 내장되어 있어 “Wi-Fi”와 “Bluetooth 5.0(BLE)”을 바로 쓸 수 있음. ㅠ

```markdown
## AT 커맨드로 역할 전환 가능 
AT+SETCFG=(ID),(역할),(속도),(필터)
                  ↑
                  0 = 태그 (Tag)
                  1 = 기지국 (Anchor)
                  

# 앵커로 설정 :
AT+SETCFG=0,1,0,1   → ID 0번 앵커
AT+SETCFG=1,1,0,1   → ID 1번 앵커
AT+SETCFG=2,1,0,1   → ID 2번 앵커
AT+SETCFG=3,1,0,1   → ID 3번 앵커
AT+SAVE
AT+RESTART

# 태그로 설정:
AT+SETCFG=0,0,0,1   → ID 0번 태그 (사람1)
AT+SETCFG=1,0,0,1   → ID 1번 태그 (사람2)
...
AT+SAVE
AT+RESTART

# 실제 구매 시나리오
동일한 MaUWB_ESP32S3 모듈을 N개 구매

    4개 → 앵커로 설정 → 천장/벽 고정
    5개 → 태그로 설정 → 각 ODROID에 USB 연결

```

가격 : 개당 100,000 정도