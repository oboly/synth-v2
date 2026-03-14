from openai import OpenAI

client = OpenAI()

print("ChatGPT terminal. Type 'exit' om te stoppen.\n")

messages = []

while True:
    user_input = input(">> ")

    if user_input.lower() in ["exit", "quit"]:
        break

    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="gpt-5.3",
        messages=messages
    )

    answer = response.choices[0].message.content

    print("\n", answer, "\n")

    messages.append({"role": "assistant", "content": answer})
