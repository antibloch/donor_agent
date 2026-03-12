# 1. Use an official lightweight Python image
FROM python:3.10-slim

# 2. Set the working directory inside the container
WORKDIR /app

# >>> NEW STEP: Install Node.js and npm (for npx) <<<
RUN apt-get update && apt-get install -y nodejs npm

# 3. Copy only the requirements file first to leverage Docker cache
COPY requirements.txt .

# 4. Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Install Playwright (Python) and browsers
RUN playwright install --with-deps chromium

# 6. Install Playwright system dependencies (Node side)
RUN npx playwright install-deps

# 7. Install Chromium browser for Playwright
RUN npx playwright install chromium

# 8. Copy the rest of your application code into the container
COPY . .

# 9. Command to run your application
CMD ["python", "main_agent.py"]
