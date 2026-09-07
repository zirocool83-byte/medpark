import production_entry as prod

app = prod.app

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = "mp001"

response = client.get("/?year=2026&month=9")
html = response.get_data(as_text=True)

checks = {
    "status_200": response.status_code == 200,
    "september_meeting": "2026년 9월 실적회의" in html,
    "second_stage": "9월 2차 예상" in html,
    "global_fcst_panel": "Global Maps 해외 FCST" in html,
    "detail_table": "상세 숫자표" in html,
    "dental_card": ">덴탈<" in html,
    "medical_card": ">메디컬<" in html,
    "aesthetic_card": ">에스테틱<" in html,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise RuntimeError("UI verification failed: " + ", ".join(failed))

print("UI verification passed:", ", ".join(checks.keys()))
