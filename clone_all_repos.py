import os
import requests
import subprocess

token = "ACCESS_TOKEN"
org_name = "ORG_NAME"
headers = {"Authorization": f"Bearer {token}"}
api_url = f"https://api.github.com/orgs/{org_name}/repos?type=all" 

if not os.path.exists(org_name):
    os.makedirs(org_name)

response = requests.get(api_url, headers=headers)
print("Status Code:", response.status_code)
print("Response JSON:", response.json())

if response.status_code == 200:
    repos = response.json()
    if repos:
        for repo in repos:
            repo_name = repo['name']
            clone_url = repo['clone_url']

            print(f"Cloning {repo_name}...")

            repo_path = os.path.join(org_name, repo_name)
            if not os.path.exists(repo_path):
                subprocess.run(["git", "clone", clone_url, repo_path])
            else:
                print(f"The repository {repo_name} already exists.")
    else:
        print("No repositories found in the organization.")
else:
    print("Error:", response.status_code, response.json())
