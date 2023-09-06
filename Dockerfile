FROM python:3.10

WORKDIR /python-docker

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip; pip3 install -r requirements.txt

COPY . .

CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0"]