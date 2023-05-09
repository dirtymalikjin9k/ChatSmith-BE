document.getElementById("send").addEventListener("click", function(event) {
    event.preventDefault();
    const query = document.getElementById("query").value;
    const botId = this.dataset.botId; // Get the bot_id from the data attribute
    const sendImage = this.querySelector("img"); // Get the send button image

    if (query) {
        // Add the user's question to the chat immediately after clicking the send button
        const chat = document.getElementById("chat");
        const userDiv = document.createElement("div");
        userDiv.classList.add("user");
        userDiv.innerHTML = "<p>" + query + "</p>";
        chat.appendChild(userDiv);

        // Change the send button image to the typing indicator
        sendImage.src = "static/assets/typing.svg";
        document.getElementById("query").value = "";

        fetch(`/api/ask?bot_id=${botId}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ query: query }),
            })
            .then((response) => response.json())
            .then((data) => {
                // Add the chatbot's response to the chat
                const chatbotDiv = document.createElement("div");
                chatbotDiv.classList.add("chatbot");
                chatbotDiv.innerHTML = "<p>" + data.response + "</p>";
                chat.appendChild(chatbotDiv);

                // Scroll the chat window to the bottom to show the new message
                chat.scrollTop = chat.scrollHeight - chat.clientHeight;

                // Clear the input field and change the send button image back to the original
                document.getElementById("query").value = "";
                sendImage.src = "static/assets/send.svg";
            })
            .catch((error) => {
                console.error("Error:", error);
            });
    }
});