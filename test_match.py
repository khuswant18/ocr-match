import requests

res = requests.get("http://localhost:5001/api/match/4010510")
print(res.status_code)
print(res.text)
