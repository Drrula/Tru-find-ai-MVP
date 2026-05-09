import csv
import requests

input_path = r"C:\Users\luxco\OneDrive\Desktop\A TruFindAI\Data\t1_100_real_leads.csv"
output_path = r"C:\Users\luxco\OneDrive\Desktop\A TruFindAI\Exports\t1_100_scored_results.csv"

with open(input_path, newline="", encoding="utf-8-sig") as infile, open(output_path, "w", newline="", encoding="utf-8") as outfile:
    reader = csv.DictReader(infile)
    reader.fieldnames = [name.strip().replace("\ufeff", "") for name in reader.fieldnames]

    fieldnames = reader.fieldnames + ["score", "gaps", "summary"]
    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
    writer.writeheader()

    for row in reader:
        payload = {
            "business_name": row["business_name"],
            "location": row["location"]
        }

        response = requests.post(
            "http://127.0.0.1:8000/analyze-business",
            json=payload
        )
        data = response.json()

        row["score"] = data.get("score", "")
        row["gaps"] = " | ".join(data.get("gaps", []))
        row["summary"] = data.get("summary", "")

        writer.writerow(row)

        print(row["business_name"], row["score"])

print("DONE - results saved to Exports folder")