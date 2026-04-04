import os
import json
import urllib.request
import urllib.error
import ssl
import streamlit as st

def _anthropic_chat(api_key: str, system_prompt: str, messages: list) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": "claude-opus-4-6",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": messages
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            data = json.loads(r.read())
            return data["content"][0]["text"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        return f"Anthropic API Error ({e.code}): {err_body}"
    except Exception as e:
        return f"Error communicating with Anthropic API: {e}"

def render(scores: dict, anomalies: dict, data: dict):
    st.markdown("## AI Risk Assistant")
    st.caption("Ask questions about protocol risk, market conditions, or your portfolio. Powered by Claude Opus.")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # Format the current system state
    system_prompt = (
        "You are an expert DeFi risk analyst assistant. Answer questions based on the live data provided. "
        "Keep your answers concise, professional, and actionable. Do not hallucinate metrics.\\n\\n"
    )
    
    system_prompt += f"### Market Context\\n"
    system_prompt += f"Fear & Greed Index: {data.get('fear_greed', {}).get('value', 'Unknown')}\\n\\n"
    
    system_prompt += "### Protocol Risk Scores\\n"
    for proto, info in scores.items():
        system_prompt += f"- {proto}: Risk={info.get('composite')}, Signal={info.get('signal')}, TVL Drawdown={info.get('drawdown_pct')}%\\n"
    
    # Initialize message memory
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # Display chat history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    # Chat Input
    if user_input := st.chat_input("Ask about high-risk protocols, anomalies, or market conditions..."):
        if not api_key:
            st.error("Please enter your Anthropic API Key in the sidebar.")
            return

        with st.chat_message("user"):
            st.markdown(user_input)
            
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = _anthropic_chat(api_key, system_prompt, st.session_state.chat_messages)
                st.markdown(response)
                
        st.session_state.chat_messages.append({"role": "assistant", "content": response})
