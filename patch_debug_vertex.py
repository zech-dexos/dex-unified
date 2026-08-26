content = open('api.py').read()

old = '    except Exception as e:\n        return {\n            "voice_response": "I\'m right here with you. Let me try that again.",\n            "response": "I\'m right here with you. Let me try that again.",\n            "device_action": None\n        }'

new = '    except Exception as e:\n        print(f"[haven_api ERROR] {type(e).__name__}: {e}")\n        return {\n            "voice_response": "I\'m right here with you. Let me try that again.",\n            "response": f"ERROR: {type(e).__name__}: {str(e)[:200]}",\n            "device_action": None\n        }'

assert 'except Exception as e:' in content
content = content.replace(old, new, 1)
open('api.py', 'w').write(content)
print("Patched OK")
