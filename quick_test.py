import requests
import json

# Test URLs
test_urls = [
    "https://www.facebook.com/facebook/videos/10153231379946729/",
]

api_url = "http://localhost:8000/download"

for video_url in test_urls:
    print(f"\nTesting: {video_url}")
    try:
        response = requests.get(api_url, params={"url": video_url})
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        # Try to parse JSON
        try:
            data = response.json()
            print(f"Response Data: {json.dumps(data, indent=2)}")
            
            if data.get('success'):
                print(f"\n✓ Success!")
                print(f"  Title: {data['data'].get('title', 'N/A')}")
                print(f"  Video URL: {data['data'].get('video_url', 'N/A')[:100]}...")
            else:
                print(f"\n✗ Failed: {data.get('message', 'Unknown error')}")
                print(f"  Error: {data.get('error', 'No error details')}")
                
        except json.JSONDecodeError as e:
            print(f"✗ JSON Parse Error: {e}")
            print(f"Raw response text: {response.text[:500]}")
            
    except Exception as e:
        print(f"✗ Request Error: {str(e)}")