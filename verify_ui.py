import production_entry as prod

app = prod.app
client = app.test_client()

with client.session_transaction() as sess:
    sess["user_id"] = "mp001"

# 1) 9월 대시보드 실제 로그인 렌더링 검증
response = client.get("/?year=2026&month=9")
html = response.get_data(as_text=True)
checks = {
    "dashboard_status_200": response.status_code == 200,
    "september_meeting": "2026년 9월 실적회의" in html,
    "second_stage": "9월 2차 예상" in html,
    "global_fcst_panel": "Global Maps 해외 FCST" in html,
    "detail_table": "상세 숫자표" in html,
    "dental_card": ">덴탈<" in html,
    "medical_card": ">메디컬<" in html,
    "aesthetic_card": ">에스테틱<" in html,
}

# 2) 9월 2차 입력 화면 실제 로그인 렌더링 검증
input_response = client.get("/input?year=2026&month=9&stage=2%EC%B0%A8&scope=%EB%8D%B4%ED%83%88%7C%EA%B5%AD%EB%82%B4")
input_html = input_response.get_data(as_text=True)
checks.update({
    "input_status_200": input_response.status_code == 200,
    "input_september": "2026년 9월" in input_html,
    "input_second_stage": "2차" in input_html,
    "input_current_total": "현재 집계" in input_html,
    "input_form": "실적 입력" in input_html,
    "input_rows": "현재 입력내역" in input_html,
})

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise RuntimeError("UI verification failed: " + ", ".join(failed))

print("UI verification passed:", ", ".join(checks.keys()))
