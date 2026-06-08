import re

with open("main.js", "r", encoding="utf-8") as f:
    content = f.read()

# Find all occurrences of "tradfi" and print surrounding text
for match in re.finditer(r"tradfi", content, re.IGNORECASE):
    start = max(0, match.start() - 200)
    end = min(len(content), match.end() + 200)
    print("--- TRADFI MATCH ---")
    print(content[start:end])

# Find all occurrences of "hip-3" or "HIP-3" and print surrounding text
for match in re.finditer(r"hip-3", content, re.IGNORECASE):
    start = max(0, match.start() - 200)
    end = min(len(content), match.end() + 200)
    print("--- HIP-3 MATCH ---")
    print(content[start:end])
