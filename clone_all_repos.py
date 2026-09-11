import os
import requests
import subprocess
import sys

token = "YOUR_TOKEN_HERE"
org_name = "ORG_NAME"
headers = {"Authorization": f"Bearer {token}"}

if not os.path.exists(org_name):
    os.makedirs(org_name)

page = 1
all_repos = []

while True:
    api_url = f"https://api.github.com/orgs/{org_name}/repos?type=all&per_page=100&page={page}"
    response = requests.get(api_url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching page {page}: {response.status_code} - {response.json()}")
        sys.exit(1)
        
    repos_page = response.json()
    if not repos_page:
        break
    all_repos.extend(repos_page)
    page += 1

print(f"Number of repos found: {len(all_repos)}")

if all_repos:
    for repo in all_repos:
        repo_name = repo['name']
        clone_url = repo['clone_url'].replace("https://", f"https://{token}@")
        print(f"Cloning {repo_name}...")
        repo_path = os.path.join(org_name, repo_name)
        if not os.path.exists(repo_path):
            subprocess.run(["git", "clone", clone_url, repo_path])
        else:
            print(f"The repository {repo_name} already exists.")
else:
    print("No repositories found in the organization.")