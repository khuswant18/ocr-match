import google.generativeai as genai

genai.configure(api_key="AIzaSyB8kivjhi39InTQ0QlRMRL3giXcq-s-H2U")

models = genai.list_models()

for model in models:
    print(model.name) 