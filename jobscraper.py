import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
from logging.handlers import TimedRotatingFileHandler
import ssl
import certifi
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

ssl._create_default_https_context = ssl._create_unverified_context


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        TimedRotatingFileHandler(
            "jobscraper.log", when="W0", interval=1, backupCount=4
        ),
        # logging.StreamHandler()
    ],
)

company_urls = {
    "APC": "https://approcess.com/careers",
    "Abbvie": "https://careers.abbvie.com/en/jobs?q=&options=&page=1&la=53.3498053&lo=-6.2603097&ln=Dublin,%20Ireland&lr=100",
    "Astrazeneca": "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2",
    # "Pfizer": "https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers?Location_Country=04a05835925f45b3a59406a2a6b72c8a&locations=e2d3979e3af101cb6c9c1a59076c3890",
    # "BMS": "https://jobs.bms.com/careers?location=ireland",
    # "MSD": "https://jobs.msd.com/gb/en/ireland-job-search?utm_source=google&utm_medium=sea&utm_campaign=emea-ie&utm_content=branded&gclid=CjwKCAjwodC2BhAHEiwAE67hJBtaWGHg5w7tWTOeXFukL141m02EHQ2NEu7zg4139IxtTg1M7wxPsRoC9JcQAvD_BwE",
    "Takeda": "https://jobs.takeda.com/search-jobs/Ireland/1113/2/2963597/53/-8/50/2",
    "Amgen": "https://www.amgen.jobs/irl/jobs/",
    "Vle therapeutics": "https://www.vletherapeutics.com/careers",
    "Astellas": "https://astellas.avature.net/en_GB/careers/SearchJobs/?1329=%5B180801%5D&1329_format=1348&listFilterMode=1&jobOffset=",
}


def APC():
    logging.info("Fetching job details for APC.")
    try:
        response = requests.get(company_urls["APC"])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        table = soup.find("table")
        rows = table.find_all("tr")[1:]
        job_details = []
        for row in rows:
            title = row.find("td", class_="title title--quaternary").text.strip()
            closing_date = row.find("td", class_="title title--senary").text.strip()
            link = row.find("a")["href"]
            job_details.append(
                {
                    "company": "APC",
                    "title": title,
                    "application link": link,
                    "closing_date": closing_date,
                    "job portal link": company_urls["APC"],
                }
            )
        logging.info(f"Fetched {len(job_details)} jobs for APC.")
        return job_details
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for APC: {e}")
        return []


def Abbvie():
    logging.info("Fetching job details for Abbvie.")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(company_urls["Abbvie"], headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        job_tiles = soup.find_all("a", class_="attrax-vacancy-tile__title")
        jobs = []
        for tile in job_tiles:
            job_title = tile.get_text(strip=True)
            job_url = tile["href"]
            jobs.append(
                {
                    "company": "Abbvie",
                    "title": job_title,
                    "application link": "https://careers.abbvie.com" + job_url,
                    "job portal link": company_urls["Abbvie"],
                }
            )
        logging.info(f"Fetched {len(jobs)} jobs for Abbvie.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Abbvie: {e}")
        return []


def Astrazeneca():
    logging.info("Fetching job details for Astrazeneca.")
    try:
        base_url = company_urls["Astrazeneca"]
        jobs = []
        page = 1
        while True:
            url = f"{base_url}/{page}"
            response = requests.get(url)
            response.raise_for_status()
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.content, "lxml")
            job_tiles = soup.find_all("a", class_="search-results-link")
            if not job_tiles:
                break
            for tile in job_tiles:
                job_title = tile.text.strip().split("\n")[0]
                job_url = tile["href"]
                jobs.append(
                    {
                        "company": "Astrazeneca",
                        "title": job_title,
                        "application url": "https://careers.astrazeneca.com/" + job_url,
                        "job portal link": company_urls["Astrazeneca"],
                    }
                )
            page += 1
        logging.info(f"Fetched {len(jobs)} jobs for Astrazeneca.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Astrazeneca: {e}")
        return []


def Takeda():
    logging.info("Fetching job details for Takeda.")
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(company_urls["Takeda"], verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        job_links = soup.find_all("a", {"data-job-id": True})
        jobs = []
        for job in job_links:
            try:
                job_title = job.find("h2", class_="title").text.strip()
            except AttributeError:
                break
            job_url = job["href"]
            jobs.append(
                {
                    "company": "Takeda",
                    "title": job_title,
                    "application url": "https://jobs.takeda.com/" + job_url,
                    "job portal link": company_urls["Takeda"],
                }
            )
        logging.info(f"Fetched {len(jobs)} jobs for Takeda.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Takeda: {e}")
        return []


def Amgen():
    logging.info("Fetching job details for Amgen.")
    try:
        response = requests.get(company_urls["Amgen"])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        job_links = soup.find_all("h4")
        jobs = []
        for job in job_links:
            job_title = job.text.strip()
            job_url = "https://www.amgen.jobs" + job.find("a")["href"]
            jobs.append(
                {
                    "company": "Amgen",
                    "title": job_title,
                    "application url": job_url,
                    "job portal link": company_urls["Amgen"],
                }
            )
        logging.info(f"Fetched {len(jobs)} jobs for Amgen.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Amgen: {e}")
        return []


def Vle():
    logging.info("Fetching job details for Vle.")
    try:
        response = requests.get(company_urls["Vle therapeutics"])
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        job_links = soup.find_all("div", class_="table-content")
        jobs = []
        for job in job_links:
            job_title = job.find("p", class_="job-description").text.strip()
            closing_date = (
                job.find("p", class_="close-date").text.strip()
                if job.find("p", class_="close-date")
                else "N/A"
            )
            job_url = job.find("a", class_="careers-link")["href"]
            jobs.append(
                {
                    "company": "Vle therapeutics",
                    "title": job_title,
                    "closing_date": closing_date,
                    "application url": job_url,
                    "job portal link": company_urls["Vle therapeutics"],
                }
            )
        logging.info(f"Fetched {len(jobs)} jobs for Vle.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Vle: {e}")
        return []


def Astellas():
    logging.info("Fetching job details for Astellas.")
    try:
        base_url = company_urls["Astellas"]
        jobs = []
        page = 0
        while True:
            url = f"{base_url}{page}"
            response = requests.get(url)
            response.raise_for_status()
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.content, "lxml")
            job_tiles = soup.find_all("h3", class_="article__header__text__title")
            if not job_tiles:
                break
            for tile in job_tiles:
                job_title = tile.text.strip()
                job_url = tile.find("a")["href"]
                jobs.append(
                    {
                        "company": "Astellas",
                        "title": job_title,
                        "application url": job_url,
                        "job portal link": url,
                    }
                )
            page += 10
        logging.info(f"Fetched {len(jobs)} jobs for Astellas.")
        return jobs
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching job details for Astellas: {e}")
        return []


def get_all_job_postings():
    logging.info("Starting to fetch all job postings.")
    all_jobs = {}
    failed_companies = []  # List to store companies that failed

    try:
        all_jobs["Abbvie"] = Abbvie()
    except Exception as e:
        failed_companies.append(f"Abbvie: {str(e)}")
        logging.error(f"Error fetching Abbvie jobs: {e}")

    try:
        all_jobs["Amgen"] = Amgen()
    except Exception as e:
        failed_companies.append(f"Amgen: {str(e)}")
        logging.error(f"Error fetching Amgen jobs: {e}")

    try:
        all_jobs["APC"] = APC()
    except Exception as e:
        failed_companies.append(f"APC: {str(e)}")
        logging.error(f"Error fetching APC jobs: {e}")

    try:
        all_jobs["Astellas"] = Astellas()
    except Exception as e:
        failed_companies.append(f"Astellas: {str(e)}")
        logging.error(f"Error fetching Astellas jobs: {e}")

    try:
        all_jobs["Astrazeneca"] = Astrazeneca()
    except Exception as e:
        failed_companies.append(f"Astrazeneca: {str(e)}")
        logging.error(f"Error fetching Astrazeneca jobs: {e}")

    try:
        all_jobs["Takeda"] = Takeda()
    except Exception as e:
        failed_companies.append(f"Takeda: {str(e)}")
        logging.error(f"Error fetching Takeda jobs: {e}")

    try:
        all_jobs["Vle therapeutics"] = Vle()
    except Exception as e:
        failed_companies.append(f"Vle therapeutics: {str(e)}")
        logging.error(f"Error fetching Vle Therapeutics jobs: {e}")

    logging.info("Completed fetching all job postings.")
    return all_jobs, failed_companies


def load_previous_jobs(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
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
            new_jobs_for_company = [
                job for job in jobs if job["title"] not in previous_titles
            ]

            if new_jobs_for_company:
                new_jobs[company] = new_jobs_for_company

    return new_jobs


def update_json_file(filename, current_jobs):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(current_jobs, f, ensure_ascii=False, indent=4)


def format_json_pretty(data):
    # Convert the data to a pretty-printed JSON string
    return json.dumps(data, ensure_ascii=False, indent=4)


def jobs_to_html_table(new_jobs):
    """Convert job data into an HTML table."""
    html = """
    <html>
    <body>
    <h2>New Job Postings</h2>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
        <tr>
            <th>Company</th>
            <th>Job Title</th>
            <th>Job Link</th>
        </tr>
    """

    # Loop through new jobs and add rows to the table
    for company, jobs in new_jobs.items():
        for job in jobs:
            title = job.get("title", "No Title")
            link = job.get("application url", "#")
            jobportal = job.get("job portal link", "#")
            html += f"""
            <tr>
                <td><a href="{jobportal}">{company}</td>
                <td>{title}</td>
                <td><a href="{link}">Apply</a></td>
            </tr>
            """

    # Close the table and HTML tags
    html += """
    </table>
    </body>
    </html>
    """

    return html


def send_email(
    subject,
    body,
    to_email,
    from_email,
    smtp_server,
    smtp_port,
    smtp_username,
    smtp_password,
):
    # Create a multipart message
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = ", ".join(to_email)
    msg["Subject"] = subject

    # Attach the body of the email
    msg.attach(MIMEText(body, "html"))

    try:
        # Create server object with SSL option
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(smtp_username, smtp_password)

        # Send the email
        server.sendmail(from_email, to_email, msg.as_string())

        # Disconnect from the server
        server.quit()

        logging.info("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email. Error: {str(e)}")
        logging.error(f"Failed to send email. Error: {str(e)}")


def main():
    json_file = "/Users/pratik/Github/Job-finder/jobs.json"
    try:
        current_jobs, failed_companies = get_all_job_postings()
        previous_jobs = load_previous_jobs(json_file)
        new_jobs = find_new_jobs(previous_jobs, current_jobs)

        # If new jobs are found, send an email notification
        if new_jobs:
            logging.info(
                f"New job postings found: {len(new_jobs)} companies with new jobs."
            )
            email_body = jobs_to_html_table(new_jobs)

            send_email(
                subject="New Job Postings Alert",
                body=email_body,
                to_email=["vaidehipatil2011@gmail.com"],
                from_email="barvepratik96@gmail.com",
                smtp_server="smtp.gmail.com",
                smtp_port=465,
                smtp_username="barvepratik96@gmail.com",
                smtp_password="qkgb oxdd etzu zqyj",
            )
            # Print new jobs
            for company, jobs in new_jobs.items():
                logging.info(f"{company}:")
                for job in jobs:
                    logging.info(json.dumps(job, ensure_ascii=False, indent=4))

        else:
            logging.info("No new job postings found.")

        # Update the JSON file with the current job postings
        update_json_file(json_file, current_jobs)
        logging.info("Job data updated successfully.")

        # If any companies failed, send an email notification
        if failed_companies:
            error_message = "\n".join(failed_companies)
            logging.error(
                f"Job fetching failed for the following companies: {error_message}"
            )
            send_email(
                subject="Job Scraper Error Notification",
                body=f"Job fetching failed for the following companies:\n{error_message}",
                to_email=["barvepratik96@gmail.com"],
                from_email="barvepratik96@gmail.com",
                smtp_server="smtp.gmail.com",
                smtp_port=465,
                smtp_username="barvepratik96@gmail.com",
                smtp_password="qkgb oxdd etzu zqyj",
            )

    except Exception as e:
        # Log the error
        logging.error(f"Error occurred: {str(e)}")
        # Send an error notification to yourself via email
        send_email(
            subject="Job Scraper Error Notification",
            body=f"An error occurred: {str(e)}",
            to_email=["barvepratik96@gmail.com"],
            from_email="barvepratik96@gmail.com",
            smtp_server="smtp.gmail.com",
            smtp_port=465,
            smtp_username="barvepratik96@gmail.com",
            smtp_password="qkgb oxdd etzu zqyj",
        )


if __name__ == "__main__":
    main()