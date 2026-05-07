import asyncio
import os
import google.generativeai as genai
from pyzeebe import ZeebeWorker, create_insecure_channel
from dotenv import load_dotenv

load_dotenv()

# Setup AI Model
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

# 1. Food Safety Task
async def evaluate_safety_agent(special_instructions: str):
    print(f"AI evaluating instructions: {special_instructions}")
    prompt = (
        f"You are a food safety agent. Review these instructions: '{special_instructions}'. "
        "If there is a mention of a severe allergy, contamination risk, or biological hazard, "
        "reply strictly with 'RISK'. Otherwise reply 'SAFE'. One word only."
    )
    try:
        response = await model.generate_content_async(prompt)
        decision = response.text.strip().upper()
        is_safe = "RISK" not in decision
        print(f"AI Decision: {'SAFE' if is_safe else 'RISK DETECTED'}")
        return {"is_safe": is_safe}
    except Exception as e:
        print(f"Safety AI Error: {e}")
        return {"is_safe": False}

# 2. Review Moderation Task
async def evaluate_review_agent(review_text: str):
    print(f"AI evaluating review: {review_text}")
    prompt = (
        f"You are a moderation agent. Review this product review: '{review_text}'. "
        "If it contains profanity, hate speech, or dangerous content, "
        "reply strictly with 'RISK'. Otherwise reply 'SAFE'. One word only."
    )
    try:
        response = await model.generate_content_async(prompt)
        decision = response.text.strip().upper()
        is_safe = "RISK" not in decision
        print(f"AI Decision: {'SAFE' if is_safe else 'RISK DETECTED'}")
        return {"is_safe": is_safe}
    except Exception as e:
        print(f"Review AI Error: {e}")
        return {"is_safe": False}

# Main Async Loop
async def main():
    #zeebe_addr = os.getenv("ZEEBE_ADDRESS", "host.docker.internal:26500")
    channel = create_insecure_channel("localhost:26500")
    worker = ZeebeWorker(channel)

    # Register both tasks (Ensure these names match your 'Job type' in Camunda!)
    worker.task(task_type="evaluate-safety-agent")(evaluate_safety_agent)
    worker.task(task_type="evaluate-review-agent")(evaluate_review_agent)

    print(f"Google AI Worker is listening for Camunda jobs on {channel}...")
    await worker.work()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping worker...")