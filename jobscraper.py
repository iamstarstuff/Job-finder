import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

company_urls = {
    "APC": "https://approcess.com/careers",
    "Abbvie": "https://careers.abbvie.com/en/jobs?q=&options=&page=1&la=53.3498053&lo=-6.2603097&ln=Dublin,%20Ireland&lr=100",
    "Astrazeneca": "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2",
    "Pfizer": "https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers?Location_Country=04a05835925f45b3a59406a2a6b72c8a&locations=e2d3979e3af101cb6c9c1a59076c3890",
    "BMS": "https://jobs.bms.com/careers?location=ireland",
    "MSD": "https://jobs.msd.com/gb/en/ireland-job-search?utm_source=google&utm_medium=sea&utm_campaign=emea-ie&utm_content=branded&gclid=CjwKCAjwodC2BhAHEiwAE67hJBtaWGHg5w7tWTOeXFukL141m02EHQ2NEu7zg4139IxtTg1M7wxPsRoC9JcQAvD_BwE",
    "Takeda": "https://jobs.takeda.com/search-jobs/Ireland/1113/2/2963597/53/-8/50/2",
    "Amgen": "https://www.amgen.jobs/irl/jobs/",
    "Vle therapeutics": "https://www.vletherapeutics.com/careers",
    "Astellas": "https://astellas.avature.net/en_GB/careers/SearchJobs/?1329=%5B180801%5D&1329_format=1348&listFilterMode=1&jobOffset="
}

def APC():
    try:
        response = requests.get(company_urls["APC"])
        response.raise_for_status()
        soup = BeautifulSoup(response.content,'lxml')
        table = soup.find('table')
        rows = table.find_all('tr')[1:]
        job_details = []
        for row in rows:
            title = row.find('td',class_='title title--quaternary').text.strip()
            closing_date = row.find('td',class_='title title--senary').text.strip()
            link = row.find('a')['href']
            job_details.append({
                'company':'APC',
                'title':title,
                'application link':link,
                'closing_date':closing_date,
                'job portal link':company_urls['APC']
            })
        return job_details
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Abbvie():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(company_urls['Abbvie'],headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        job_tiles = soup.find_all('a', class_='attrax-vacancy-tile__title')
        jobs = []
        for tile in job_tiles:
            job_title = tile.get_text(strip=True)
            job_url = tile['href']
            jobs.append({
                'company':'Abbvie',
                'title': job_title,
                'application link': 'https://careers.abbvie.com'+job_url,
                'job portal link':company_urls['Abbvie']
                })
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Astrazeneca():
    try:   
        base_url = company_urls['Astrazeneca']
        jobs = []
        page=1
        while True:
            url=f'{base_url}/{page}'
            response = requests.get(url)
            response.raise_for_status()
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.content,'lxml')
            job_tiles = soup.find_all('a',class_='search-results-link')
            if not job_tiles:
                break
            for tile in job_tiles:
                job_title = tile.text.strip().split('\n')[0]
                job_url = tile['href']
                jobs.append({
                    'company':'Astrazeneca',
                    'title':job_title,
                    'application url':'https://careers.astrazeneca.com/'+job_url,
                    'job portal link': company_urls['Astrazeneca']
                })
            page+=1
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Takeda():
    try:
        response = requests.get(company_urls['Takeda'])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        job_links = soup.find_all('a', {'data-job-id': True})
        jobs = []
        for job in job_links:
            try:
                job_title = job.find('h2', class_='title').text.strip()
            except AttributeError:
                break
            job_url = job['href']
            jobs.append({
                'company':'Takeda',
                'title':job_title,
                'application url':'https://jobs.takeda.com/'+job_url,
                'job portal link':company_urls['Takeda']
            })
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Amgen():
    try:
        response = requests.get(company_urls['Amgen'])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        job_links = soup.find_all('h4')
        jobs = []
        for job in job_links:
            job_title = job.text.strip()
            job_url = 'https://www.amgen.jobs/'+job.find('a')['href']
            jobs.append({
                'company':'Amgen',
                'title':job_title,
                'application url':job_url,
                'job portal link':company_urls['Amgen']
            })
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Vle():
    try:
        response = requests.get(company_urls['Vle therapeutics'])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        job_links = soup.find_all('div',class_='table-content')
        jobs = []
        for job in job_links:
            job_title = job.find('p', class_='job-description').text.strip()
            closing_date = job.find('p', class_='close-date').text.strip() if job.find('p', class_='close-date') else 'N/A'
            job_url = job.find('a', class_='careers-link')['href']
            jobs.append({
                'company':'Vle therapeutics',
                'title': job_title,
                'closing_date': closing_date,
                'application url': job_url,
                'job portal link': company_urls['Vle therapeutics']
            })
        return jobs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job details: {e}")
        return []

def Astellas():    
    try:
        base_url = company_urls['Astellas']
        jobs = []
        page = 0
        while True:
            url=f'{base_url}{page}'
            response = requests.get(url)
            response.raise_for_status()
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.content, 'lxml')
            job_tiles = soup.find_all('h3', class_='article__header__text__title')
            if not job_tiles:
                break
            for tile in job_tiles:
                job_title = tile.text.strip()
                job_url = tile.find('a')['href']
                jobs.append({
                    'company':'Astellas',
                    'title':job_title,
                    'application url':job_url,
                    'job portal link':url
                })
            page+=10
        return jobs
    except requests.exceptions.RequestException as e:
            print(f"Error fetching job details: {e}")
            return []

def get_all_job_postings():
    all_jobs = {}

    
    all_jobs["Abbvie"] = Abbvie()
    all_jobs["Amgen"] = Amgen()
    all_jobs["APC"] = APC()
    all_jobs['Astellas'] = Astellas()
    all_jobs["Astrazeneca"] = Astrazeneca()
    all_jobs["Takeda"] = Takeda()
    all_jobs['Vle therapeutics'] = Vle()
    

    return all_jobs

def load_previous_jobs(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    else:
        return {}

def find_new_jobs(previous_jobs, current_jobs):
    new_jobs = {}
    
    for company, jobs in current_jobs.items():
        if company not in previous_jobs:
            new_jobs[company] = jobs
        else:
            previous_titles = {job["title"] for job in previous_jobs[company]}
            new_jobs_for_company = [job for job in jobs if job["title"] not in previous_titles]
            
            if new_jobs_for_company:
                new_jobs[company] = new_jobs_for_company
    
    return new_jobs

def update_json_file(filename, current_jobs):
    with open(filename, 'w') as f:
        json.dump(current_jobs, f, indent=4)

# def main():
#     json_file = "jobs.json"
#     current_jobs = get_all_job_postings()
#     previous_jobs = load_previous_jobs(json_file)
#     new_jobs = find_new_jobs(previous_jobs, current_jobs)
#     if new_jobs:
#         print("New job postings found:")
#         for company, jobs in new_jobs.items():
#             print(f"\n{company}:")
#             for job in jobs:
#                 print(job)
#     else:
#         print("No new job postings found.")
#     update_json_file(json_file, current_jobs)

def format_json_pretty(data):
    # Convert the data to a pretty-printed JSON string
    return json.dumps(data, indent=4)

def send_email(subject, body, to_email, from_email, smtp_server, smtp_port, smtp_username, smtp_password):
    # Create a multipart message
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = ', '.join(to_email)
    msg['Subject'] = subject
    
    # Attach the body of the email
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        # Create server object with SSL option
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(smtp_username, smtp_password)
        
        # Send the email
        server.sendmail(from_email, to_email, msg.as_string())
        
        # Disconnect from the server
        server.quit()
        
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email. Error: {str(e)}")

def main():
    json_file = "jobs.json"
    current_jobs = get_all_job_postings()
    previous_jobs = load_previous_jobs(json_file)
    new_jobs = find_new_jobs(previous_jobs, current_jobs)
    # If new jobs are found, send an email notification
    if new_jobs:
        print("New job postings found:")
        email_body = "New job postings found:\n\n"
        for company, jobs in new_jobs.items():
            email_body += f"{company}:\n"
            for job in jobs:
                email_body += f"{format_json_pretty(job)}\n"
            email_body += "\n"
        
        send_email(
            subject="New Job Postings Alert",
            body=email_body,
            to_email=["vaidehipatil2011@gmail.com","barvepratik96@gmail.com"], 
            from_email="barvepratik96@gmail.com", 
            smtp_server="smtp.gmail.com", 
            smtp_port=465, 
            smtp_username="barvepratik96@gmail.com", 
            smtp_password="qkgb oxdd etzu zqyj" 
        )
        
        # Print new jobs 
        for company, jobs in new_jobs.items():
            print(f"\n{company}:")
            for job in jobs:
                print(job)
    else:
        print("No new job postings found.")
    
    # Update the JSON file with the current job postings
    update_json_file(json_file, current_jobs)


if __name__ == "__main__":
    main()