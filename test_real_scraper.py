import time
import httpx
import sys

BASE_URL = "http://localhost:8000/api/scrape"

def run_real_test(url: str, query: str):
    print(f"\n--- Testing with Real URL: {url} ---")
    print(f"Query: {query}")
    
    # 1. Send scrape/analyze job
    endpoint = f"{BASE_URL}/analyze"
    payload = {
        "url": url,
        "query": query,
        "timeout_ms": 30000
    }
    
    try:
        print(f"Sending POST request to {endpoint}...")
        response = httpx.post(endpoint, json=payload, timeout=10.0)
        if response.status_code != 202:
            print(f"[ERROR] Error submitting job: Status Code {response.status_code}")
            print(response.text)
            return
        
        job_data = response.json()
        job_id = job_data.get("job_id")
        print(f"[OK] Job successfully submitted! Job ID: {job_id}")
        
    except httpx.RequestError as e:
        print(f"[ERROR] Connection error: Could not connect to API at {BASE_URL}. Is Docker running?")
        print(str(e))
        return

    # 2. Poll status endpoint until DONE or FAILED
    status_url = f"{BASE_URL}/status/{job_id}"
    print(f"Polling job status at {status_url}...")
    
    max_retries = 30
    retry_interval = 2.0
    
    for i in range(max_retries):
        try:
            status_response = httpx.get(status_url)
            if status_response.status_code != 200:
                print(f"[ERROR] Error polling job: Status Code {status_response.status_code}")
                break
                
            status_data = status_response.json()
            job_status = status_data.get("status")
            print(f"[{i+1}/{max_retries}] Status: {job_status}")
            
            if job_status == "done":
                print("\n[SUCCESS] Scraping and Analysis COMPLETED successfully!")
                print("\n--- LLM Response / Analysis: ---")
                print(status_data.get("result"))
                return
            elif job_status == "failed":
                print(f"\n[ERROR] Job FAILED. Error: {status_data.get('error')}")
                return
                
        except Exception as e:
            print(f"Warning: polling failed: {str(e)}")
            
        time.sleep(retry_interval)
        
    print("\n[TIMEOUT] Job timed out or exceeded max retries.")

if __name__ == "__main__":
    # Test cases
    test_cases = [
        ("https://example.com", "Bu sitenin amaci nedir? Aciklamasini ve basligini belirt."),
        ("https://books.toscrape.com", "List the first 3 books on this page, including their titles, prices, and ratings.")
    ]
    
    for url, query in test_cases:
        run_real_test(url, query)

