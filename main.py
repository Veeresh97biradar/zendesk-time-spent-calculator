from zdesk import Zendesk
from datetime import datetime
import math
from datetime import timedelta
import os
import requests
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth

def get_author_mapping(zendesk):
    """
    Fetches the author mapping from Zendesk and returns a dictionary mapping author IDs to names.
    """
    author_mapping = {}
    
    # Fetching agent users
    response = zendesk.users_list(query={'role': 'agent'}, get_all_pages=True)
    users = response.get('users', [])
    for user in users:
        author_mapping[user['id']] = user['name']

    # Fetching admin users
    response = zendesk.users_list(query={'role': 'admin'}, get_all_pages=True)
    users = response.get('users', [])
    for user in users:
        author_mapping[user['id']] = user['name']

    return author_mapping 

def get_custom_status_mapping():
    """
    Returns the custom status mapping dictionary. There is no function to fetch this from Zdesk library, so used a  static mapping.
    """
    load_dotenv()
    url = f"https://{os.getenv('ZENDESK_DOMAIN')}.zendesk.com/api/v2/custom_statuses.json"
    response = requests.get(url, auth=HTTPBasicAuth(os.getenv('ZENDESK_EMAIL'), os.getenv('ZENDESK_PASSWORD')))

    if response.status_code == 200:
        data = response.json()
    
    custom_status = data['custom_statuses']
    custom_status_mapping = {status['id']: status['agent_label'] for status in custom_status}
    #custom_status_mapping = {8593946: 'New', 8593966: 'Open', 48501370509721: 'Open-Picked', 49279301965209: 'Waiting On TAM', 49281796392985: 'Picked', 49281950587801: 'Priortized', 8593986: 'Pending on customer Information', 49279337489049: 'Waiting On Customer ', 49281922002073: 'Backlog', 8594006: 'On-hold', 49073475708569: 'Triaged', 49519469213081: 'Prioritized', 49950013777177: 'On-Hold - Pending with TAM', 8594026: 'Solved - RCA shared', 22158910348953: 'Solved - Waiting on customer confirmation', 22158957615129: 'Solved - RCA pending', 22158975648537: 'Solved - RCA Not Available', 47864889132057: 'Solved - Confirmed', 48425190835481: 'Solved - Referred to L2', 49729092333465: 'Invalid Request', 49729132567961: 'Delivered'}
    return custom_status_mapping

def get_zendesk_client():
    """
    Returns a Zendesk client instance with the necessary credentials.
    """
    load_dotenv()  # Loads variables from a .env file into environment

    return Zendesk(
        zdesk_url=os.getenv('ZENDESK_URL'),
        zdesk_email=os.getenv('ZENDESK_EMAIL'),
        zdesk_password=os.getenv('ZENDESK_PASSWORD'),
        zdesk_token=os.getenv('ZENDESK_TOKEN', 'False') == 'True'
    )

def fetch_ticket_audits(zendesk, ticket_id):
    response = zendesk.ticket_audits(ticket_id=ticket_id, get_all_pages=True)
    return response['audits']

def build_audits_final(audits):
    global author_mapping, custom_status_mapping
    audits_final = []
    for audit in audits:
        for event in audit.get('events', []):
            if event.get('field_name') == 'custom_status_id' and event.get('type') == 'Change':
                custom_status_curr = event.get('value')
                custom_status_curr_label = custom_status_mapping.get(int(custom_status_curr), "Unknown Status")
                author_id = audit.get('author_id')
                author_name = author_mapping.get(author_id, "Unknown Author")
                created_ts = audit.get('created_at')
                audits_final.append({
                    "agent": author_name,
                    "timestamp": created_ts,
                    "status": custom_status_curr_label
                })
    return audits_final

def calculate_agent_times(audits_final):
    agent_times = {}
    for i in range(len(audits_final) - 1):
        current = audits_final[i]
        next_event = audits_final[i + 1]
        if current['status'] == 'Open-Picked':
            start_time = datetime.strptime(current['timestamp'], "%Y-%m-%dT%H:%M:%SZ")
            end_time = datetime.strptime(next_event['timestamp'], "%Y-%m-%dT%H:%M:%SZ")
            duration_minutes = (end_time - start_time).total_seconds() / 60
            agent = next_event['agent']
            agent_times[agent] = agent_times.get(agent, 0) + duration_minutes
    
    for agent in agent_times:
        agent_times[agent] = math.ceil(agent_times[agent] / 30) * 0.5  
        agent_times[agent] = round(agent_times[agent] * 2) / 2
    return agent_times

def get_ticket_details(zendesk, ticket_id):
    response = zendesk.ticket_show(ticket_id=ticket_id)
    return response['ticket']

def generate_field_data(agent_times, assignee_name):
    secondary_working_hours_log = agent_times.copy()
    if assignee_name in secondary_working_hours_log:
        secondary_working_hours_log.pop(assignee_name)

    #calculate total working hours for the assignee & secondary agents.
    assignee_working_hours = agent_times.get(assignee_name, 0)
    secondary_working_hours = sum(secondary_working_hours_log.values())
    
    #rounding them off to not mess up the tags in the dropdown values. 
    secondary_working_hours = int(secondary_working_hours) if secondary_working_hours == int(secondary_working_hours) else secondary_working_hours
    assignee_working_hours = int(assignee_working_hours) if assignee_working_hours == int(assignee_working_hours) else assignee_working_hours

    data = {
        "assignee_name": assignee_name,
        "secondary_log": secondary_working_hours_log,
        "total_secondary_working": secondary_working_hours,
        "assignee_working_hours": assignee_working_hours
    }

    print(data)
    print(agent_times)
    return data

def update_ticket(zendesk, ticket_id, field_data):
    multi_line_value = '\n'.join(f"{name}: {value}" for name, value in field_data['secondary_log'].items())
    status = 0
    data = {
    "ticket": {
      "custom_fields": [
        {
          "id": 49404020253849,
          "value": "{}_assignee".format(field_data.get("assignee_working_hours", "Unknown"))
        },
        {
          "id": 49404118763673,
          "value": "{}_secondary".format(field_data.get("total_secondary_working", "Unknown"))
        },
        {
            "id": 49454188329241,
            "value": multi_line_value
        }
      ]
    }
  }
    response = zendesk.ticket_update(ticket_id=ticket_id, data=data)
    if response.get('ticket'):
        print(f"Ticket {ticket_id} updated successfully.")
    else:
        print(f"Failed to update ticket {ticket_id}. Response: {response}")
        status = 1
    return status

def fetch_required_tickets(zendesk):
    now = datetime.now()
    now = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    print('_' * 40)
    print(f"Current time: {now}")

    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
    print("Three days ago time: {}".format(three_days_ago))
    print('_' * 40)
    query = 'group_id:6338786491161 type:ticket status:solved updated>={}'.format(three_days_ago)
    response = zendesk.search(get_all_pages=True, query=query)
    data = response.get('results', [])
    required_tickets = [ticket['id'] for ticket in data]

    print(f"Tickets updated in the last 3 days: {len(required_tickets)}")
    
    return required_tickets

def process_ticket(ticket_id):
    global author_mapping
    print(f"Processing ticket ID: {ticket_id}")
    audits = fetch_ticket_audits(get_zendesk_client(), ticket_id)
    audits_filtered = build_audits_final(audits)
    agent_times = calculate_agent_times(audits_filtered)
    assignee_id = get_ticket_details(get_zendesk_client(), ticket_id)['assignee_id']
    assignee_name = author_mapping.get(assignee_id, "Unknown Assignee")
    field_data = generate_field_data(agent_times, assignee_name)
    status = update_ticket(get_zendesk_client(), ticket_id, field_data)
    return status

def main():
    global author_mapping, custom_status_mapping
    author_mapping = get_author_mapping(get_zendesk_client())
    custom_status_mapping = get_custom_status_mapping()
    tickets = fetch_required_tickets(get_zendesk_client())
    failed_tickets = []

    webhook_url = "https://hooks.slack.com/triggers/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"
    

    for ticket_id in tickets:
        print('_' * 40)
        status = process_ticket(ticket_id)
        if status != 0:
            failed_tickets.append(ticket_id)
        print('_' * 40)
    
    if failed_tickets:
        print(f"Failed to process the following tickets: {failed_tickets}")
    else:
        print("All tickets processed successfully.")
    
    
    if failed_tickets:
        failure_payload = {"failed_tickets": str(failed_tickets)}
        response = requests.post(webhook_url, json=failure_payload)
        print(response.status_code)
        print(response.text)

if __name__ == "__main__":
    main()
