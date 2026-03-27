import requests

# Assuming invoice_item_id=95 is the one we want to map
data = {
    "invoice_item_id": 95,
    "product_code": "2751"
}
res = requests.post("http://localhost:5001/api/match/update-code", json=data)
print(res.status_code)
print(res.text)
