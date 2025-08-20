import requests
from requests.auth import HTTPBasicAuth

subdomain = 'domain'
email = 'email'
password = 'pw'  

url = f"https://{subdomain}.zendesk.com/api/v2/custom_statuses.json"
response = requests.get(url, auth=HTTPBasicAuth(email, password))

if response.status_code == 200:
    data = response.json()

custom_status = data['custom_statuses']
custom_status_mapping = {status['id']: status['agent_label'] for status in custom_status}
print(custom_status_mapping)
