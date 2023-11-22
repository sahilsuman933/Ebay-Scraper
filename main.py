import os
import pandas as pd
import glob
import httpx
import base64
from datetime import datetime
from dotenv import load_dotenv
import asyncio

load_dotenv()


def load_csv():
    files = glob.glob('./inputs/*.csv')
    df_list = []

    for f in files:
        csv = pd.read_csv(f, dtype={'upc': 'str'})
        df_list.append(csv)

    if len(df_list) == 0:
        raise Exception("No csv file found in the inputs folder.")
    data = pd.concat(df_list)
    return data.to_dict("records")


async def get_data(data, access_token):
    curr_time = datetime.now()

    async def log_request(request):
        print(f"{curr_time}: Request event hook: {request.method} {request.url} - Waiting for response")

    async def log_response(response):
        request = response.request
        print(f"{curr_time}: Response event hook: {request.method} {request.url} - Status {response.status_code}")

    async with httpx.AsyncClient(event_hooks={'request': [log_request], 'response': [log_response]}) as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        fields_to_try = ['upc', 'name']

        for field in fields_to_try:
            query_value = data.get(field)
            if pd.isna(data["Product name"]):
                if query_value and not pd.isna(query_value):
                    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={str(query_value)}"

                    # Retry mechanism
                    for attempt in range(3):
                        try:
                            response = await client.get(url, headers=headers)
                            if response.status_code == 200:
                                json_data = response.json()
                                if json_data.get('itemSummaries') is None:
                                    continue
                                data["Product name"] = json_data.get('itemSummaries')[0].get("title")
                                data["ebay cat #"] = json_data.get('itemSummaries')[0]["leafCategoryIds"][0]
                                message = ""

                                categories = json_data.get('itemSummaries')[0]["categories"]
                                for i, category_name in enumerate(categories):
                                    message += category_name.get("categoryName")
                                    if i < len(categories) - 1:
                                        message += " > "

                                data["ebay cat name"] = message
                                return
                            else:
                                print(f"Attempt {attempt + 1}: Error fetching data for {field}: {response.text}")
                                if attempt == 2:
                                    print("Max retries reached. Moving to next field.")
                                    break
                        except (httpx.RequestError, httpx.HTTPStatusError) as e:
                            print(f"Attempt {attempt + 1}: Error: {e}")
                            if attempt == 2:
                                print("Max retries reached. Moving to next field.")
                                break
            elif not pd.isna(data["Product name"]):
                print("Skipping...data is already present.")
                return

    print("No valid data found in any field")


async def get_ebay_auth_token(client_id, client_secret):
    time = datetime.now()

    async def log_request(request):
        print(f"{time}: Request event hook: {request.method} {request.url} - Waiting for response")

    async def log_response(response):
        request = response.request
        print(f"{time}: Response event hook: {request.method} {request.url} - Status {response.status_code}")

    async with httpx.AsyncClient(event_hooks={'request': [log_request], 'response': [log_response]}) as client:
        url = "https://api.ebay.com/identity/v1/oauth2/token"
        credentials = f"{client_id}:{client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_credentials}"
        }
        body = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope"
        }
        response = await client.post(url, headers=headers, data=body)

        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print("Failed to obtain token:", response.text)
            return None


async def run():
    input_data = load_csv()
    access_token = await get_ebay_auth_token(os.environ.get("CLIENT_ID"), os.environ.get("CLIENT_SECRET"))
    print(access_token)
    semaphore = asyncio.Semaphore(100)

    async def limited_get_data(data):
        async with semaphore:
            await get_data(data, access_token)
            await asyncio.sleep(0.2)

    tasks = [limited_get_data(data) for data in input_data]
    await asyncio.gather(*tasks)

    input_data = pd.DataFrame(input_data)
    input_data.to_csv(f"./outputs/results.csv", index=False)


def main():
    asyncio.run(run())


if __name__ == '__main__':
    main()
