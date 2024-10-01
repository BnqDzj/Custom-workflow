import requests
import os
from urllib.parse import quote

# 配置你的GitHub用户名和token
GITHUB_USERNAME = "BnqDzj"
GITHUB_TOKEN = os.environ["PAT"]
API_URL = "https://api.github.com"

# 获取用户所有包
def list_packages():
    url = f"{API_URL}/users/{GITHUB_USERNAME}/packages?package_type=container&per_page=100"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"获取包失败，状态码：{response.status_code}")
        return []

# 删除指定包，处理包名中的 `/`
def delete_package(package_name):
    encoded_package_name = quote(package_name, safe='')  # 将包名中的 `/` 替换为 `%2F`
    url = f"{API_URL}/users/{GITHUB_USERNAME}/packages/container/{encoded_package_name}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    response = requests.delete(url, headers=headers)
    
    if response.status_code == 204:
        print(f"包 {package_name} 删除成功")
    else:
        print(f"删除包 {package_name} 失败，状态码：{response.status_code}")

# 批量删除所有包
def delete_all_packages():
    packages = list_packages()
    for package in packages:
        package_name = package["name"]
        delete_package(package_name)

if __name__ == "__main__":
    delete_all_packages()
