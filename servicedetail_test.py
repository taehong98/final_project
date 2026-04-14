import requests
import json

SERVICE_KEY = "0ebcabb83680714dc5de0b5586984b2f57c93eb85763596634c8d2ff6bb19631"
BASE_URL = "https://api.odcloud.kr/api/gov24/v3/serviceDetail"

service_ids = ["646000000136", "449000000525"]

for service_id in service_ids:
    params = {
        "serviceKey": SERVICE_KEY,
        "serviceId": service_id,
        "returnType": "JSON",
    }

    response = requests.get(BASE_URL, params=params, timeout=30)
    print(f"\n요청 serviceId = {service_id}")
    print("요청 URL =", response.url)
    print("status =", response.status_code)

    data = response.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))

    first = data.get("data", [{}])[0]
    print("응답 서비스ID =", first.get("서비스ID"))
    print("응답 서비스명 =", first.get("서비스명"))