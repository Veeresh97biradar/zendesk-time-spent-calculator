from zdesk import Zendesk
from datetime import datetime
import math
from datetime import timedelta
import os
import requests
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import time

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
        zdesk_token=os.getenv('ZENDESK_TOKEN', 'False') == 'True')

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
        "assignee_working_hours": assignee_working_hours}



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

    group_ids = ["44897999201817", "6338786491161"]

    base_filters_common = [
        "type:ticket",
        "status:solved",
        "custom_field_50256840004505:false",
        f"updated>={three_days_ago}"
    ]

    custom_field_values = {
        "issue_": ["50124257287449", "47413823762713"],
        "query_": ["47496875391641", "50107781782681"]
    }

    mapping = {"47496875391641": "query_old_form", "50107781782681": "query_new_form", "50124257287449": "issue_new_form", "47413823762713": "issue_old_form", "44897999201817": "l1 support form", "6338786491161": "general escalation"}

    for group_id in group_ids:
        for cf_value, form_ids in custom_field_values.items():
            for form_id in form_ids:
                query = " ".join(
                    base_filters_common + [
                        f"group_id:{group_id}",
                        f"custom_field_6343868668825:{cf_value}",
                        f"ticket_form_id:{form_id}"
                    ]
                )
                print("executing the query: ")
                print(query)
                filterss = [three_days_ago]
                response = zendesk.search(get_all_pages=True, query=query)
                data = response.get('results', [])
                for event in query.split():
                    for k in event.split(':'):
                        if k in mapping:
                            filterss.append(mapping[k])
                print("Filters applied for this batch are: {data}".format(data=filterss))
                print("number of results for this batch is: {data}".format(data=len(data)))
                print('*' * 40)
                tickets.extend(data)

    required_tickets = list({ticket['id'] for ticket in tickets})  

    print(f"Tickets updated in the last 30 days: {len(required_tickets)}")
    print("List of ticket IDs:")
    print(required_tickets)
    return required_tickets

def process_ticket(ticket_id):
    global author_mapping
    print(f"Processing ticket ID: {ticket_id}")
    audits = fetch_ticket_audits(get_zendesk_client(), ticket_id)
    audits_filtered = build_audits_final(audits)
    agent_times = calculate_agent_times(audits_filtered)
    assignee_id = get_ticket_details(get_zendesk_client(), ticket_id)['assignee_id']
    assignee_name = author_mapping.get(assignee_id, "Unknown Assignee")
    working_hours_is_zero = False
    field_data = generate_field_data(agent_times, assignee_name)
    if field_data['assignee_working_hours'] == 0 and field_data['total_secondary_working'] == 0:
        print(f"Both assignee and secondary working hours are zero for ticket ID: {ticket_id}")
        working_hours_is_zero = True

    status = update_ticket(get_zendesk_client(), ticket_id, field_data)

    return status, [working_hours_is_zero, assignee_name]

def main():
    global author_mapping, custom_status_mapping
    load_dotenv()
    zendesk_client = get_zendesk_client()
    failed_tickets, empty_tickets = [], []

    author_mapping = get_author_mapping(zendesk_client)
 
    custom_status_mapping = get_custom_status_mapping()
    tickets = fetch_required_tickets(zendesk_client)
    webhook_url_empty_tickets = os.getenv("SLACK_WEBHOOK_URL_EMPTY")
    webhook_url_failed_tickets = os.getenv("SLACK_WEBHOOK_URL_FAILED")

    slack_mapping = {
    "Dimple MK": "U038P9A4CNS",
    "Monica Patel": "U02LTRN6BK9",
    "Muskan Kesharwani": "U02M82VVCBU",
    "Sudhanshu Sharan": "U02C3UAGKSL",
    "Veeresh Biradar": "U030G8ZE4KE",
    "Madanlal Bidiyasar": "U04Q8DXBS3S",
    "Anmol Baunthiyal": "U04PKQEEASZ",
    "Harmanjot Kaur": "U071MGJ56PL",
    "khushi.s@hevodata.com": "U073HQ3HM3L",
    "sthitapragyan.rout@hevodata.com": "U073HLQCWUT",
    "Vijaysree Kalvakolanu": "U05H38YSPJA",
    "Parthiv Patel": "U04Q2NV4QU9",
    "Jashmitha CG": "U05HSJWAYSC",
    "Bhuvana.K": "U05HSSD0UAC",
    "siddhartha.chauhan@hevodata.com": "U04PQ432YSE",
    "Mrinmayee Deshpande": "U090Y8SG1DJ",
    "Nimisha James": "U091LJZ776U",
    "Amruta Patil": "U090QAZSGVC",
    "Kanad Kolhe": "U091LJQEWGG",
    "Jatin Patil": "U0919MULBCH",
    "Atharva Ghanekar": "U091LKG8C0Y",
    "Harita Joshi": "U091LJR72Q0",
    "Rohit Guntuku": "U02BSMUAKAM",
    "Sarthak Bhardwaj": "U031DU0MR47",
    "Satyam Agrawal": "U031WTFFKL4",
    "Vishnu Bhargav": "U02BL86G5SQ",
    "Subham Bansal": "U02BB29SF6Z",
    "Nishant Tandon": "U031V80LK3M",
    "Kaustubh Vatsa": "U073WE8P9CZ",
    "bhuvana.k@hevodata.com": "U05HSSD0UAC"}
    for ticket_id in tickets:
        print('_' * 40)
        status, working_hours_is_zero = process_ticket(ticket_id)

        if status != 0:
            failed_tickets.append([ticket_id, working_hours_is_zero[1]])
        
        if working_hours_is_zero[0]:
            empty_tickets.append([ticket_id, working_hours_is_zero[1]])

        print('_' * 40)
    
    time.sleep(5)
    print(failed_tickets)
    print(empty_tickets)
    if empty_tickets:
        headers = {"Content-Type": "application/json"}
        iter = 0
        for ticket_id, name in empty_tickets:
            slack_id = slack_mapping.get(name)
            if slack_id:  
                payload = {
                    "slack_member_id": slack_id,
                    "empty_tickets": str(ticket_id)  
                }
            
            else:
                payload = {
                    "slack_member_id": "unknown",
                    "empty_tickets": str(ticket_id)
                }
            iter += 1
            if iter%3 == 0:
                time.sleep(5)
            response = requests.post(webhook_url_empty_tickets, json=payload, headers=headers)
            print(f"Sent payload: {payload} | with response: {response.status_code}")
            print("_" * 40)
    
    if failed_tickets:
        grouped = {}
        headers = {"Content-Type": "application/json"}
        for ticket_id, name in failed_tickets:
            slack_id = slack_mapping.get(name)
            if slack_id: 
                grouped.setdefault(slack_id, []).append(ticket_id)

        iter = 0
        for slack_id, tickets in grouped.items():
            tickets_str = ", ".join(map(str, tickets))  
            payload = {
                "slack_member_id": slack_id,
                "failed_tickets": tickets_str
            }
            iter += 1
            if iter%3 == 0:
                time.sleep(5)
            response = requests.post(webhook_url_failed_tickets, json=payload, headers=headers)
        print(f"Sent payload: {payload} | with response: {response.status_code} and response message: {response.text}")

if __name__ == "__main__":
    main()
