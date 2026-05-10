import urllib.request
import json
import urllib.error

url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=AIzaSyDAFPR41nT4a6kRI-xXcVhIvBEjcdsw54E'
data = json.dumps({'contents':[{'parts':[{'text':'Say OK'}]}]}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

try:
    res = urllib.request.urlopen(req)
    print("SUCCESS: ", res.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f'ERROR {e.code}')
    print(e.read().decode('utf-8'))
