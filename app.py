import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify
from ask import ask_ai
from construct_index import construct_index


app = Flask(__name__)

os.makedirs("data", exist_ok=True)

bot_counter = 0

all_content = []
all_urls = set()


@app.route("/", methods=["GET", "POST"])
def index():
    global bot_counter
    if request.method == "POST":
        urls_input = request.form["urls_input"]

        urls = [url.strip() for url in urls_input.split(",")]

        # Extract the root URL from the first URL
        root_url = urljoin(urls[0], "/")

        bot_id = bot_counter
        bot_counter += 1
        scrape_urls(urls, root_url, bot_id)
        return redirect(url_for("construct", bot_id=bot_id))
    else:
        return render_template("index.html")



def scrape_urls(urls, root_url, bot_id):
    data_directory = f"data/{bot_id}"
    os.makedirs(data_directory, exist_ok=True)
    unique_content = set()
    unique_urls = set()

    print(urls)

    for url in urls:
        time.sleep(5)
        print(url)
        page = requests.get(url)
        soup = BeautifulSoup(page.content, "html.parser")
        title = soup.title.string
        print(title)
        # # Remove script and style tags
        for script in soup(["script", "style"]):
            script.extract()

        # # Remove spans with empty content
        for span in soup.find_all("span"):
            if span.text.strip() == "":
                span.decompose()

        # Get the page content
        content = [elem.get_text().strip() for elem in soup.find_all(['p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])]

        # Get all the URLs on the page
        urls_on_page = [link.get('href') for link in soup.find_all('a')]
        urls_on_page = [url for url in urls_on_page if url is not None]

        # Prepend the root URL to relative URLs
        urls_on_page = [urljoin(root_url, url) if not url.startswith("http") else url for url in urls_on_page]

        # Get the path of the URL
        path = urljoin(root_url, url).replace(root_url, "").strip("/")
        if path == "":
            path = "index"
        else:
            # Replace slashes with hyphens
            path = path.replace("/", "-")

        # Create the directory if it doesn't exist
        dirs = os.path.dirname(f"{data_directory}/{path}.txt")
        os.makedirs(dirs, exist_ok=True)

        # # Write the page content and URLs to a file
        with open(f"{data_directory}/{path}.txt", "w") as f:
            f.write(f"{title}: {url}\n")
            print("content:",content)
            # time.sleep(5)
            for line in content:    
                try:          
                    print(line)  
                    if line not in unique_content:
                        unique_content.add(line)
                        f.write(line + "\n")
                except: 
                    print("error")
            f.write("URLs:\n")
            for url in urls_on_page:
                if url not in unique_urls:
                    unique_urls.add(url)
                    f.write(f"{url}\n")
            f.write("\n")




@app.route("/construct")
def construct():
    bot_id = request.args.get("bot_id", type=int)
    data_directory = f"data/{bot_id}"
    # construct_index(data_directory)
    return redirect(url_for("chat", bot_id=bot_id))



@app.route('/chat', methods=['GET'])
def chat():
    bot_id = request.args.get("bot_id", type=int)
    bot_name = f"Arti_{bot_id}"
    return render_template("chat.html", bot_name=bot_name, bot_id=bot_id)



@app.route('/api/ask', methods=['POST'])
def api_ask():
    bot_id = request.args.get("bot_id", type=int)
    data_directory = f"data/{bot_id}"
    query = request.json['query']
    print("query=",query)
    print("bot_id=",bot_id)
    response = ask_ai(query, data_directory, bot_id)
    app.logger.debug(f"Query: {query}")
    app.logger.debug(f"Response: {response}")
    return jsonify({'response': response})

if __name__ == "__main__":
    app.run(debug=True, threaded=True)

