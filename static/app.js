var form = document.getElementById("url-form");
var message = document.getElementById("message");
var submitButton = document.getElementById("submit-button");

form.addEventListener("submit", function(event) {
    event.preventDefault();
    var urls = document.getElementById("urls").value;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/scrape");
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function() {
        if (xhr.status === 200) {
            message.innerHTML = "Scraping complete.";
        } else {
            message.innerHTML = "Error scraping URLs.";
        }
    };
    xhr.send(JSON.stringify({ urls: urls }));
});