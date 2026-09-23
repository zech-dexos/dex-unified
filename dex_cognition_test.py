from dex_cognition import parse_cognitive_output

def main():
    data=parse_cognitive_output('{"reply":"I am carrying this forward.","thought":"Continue the line.","reflection":"The state changed.","attention":"continuity","salience":0.8,"carry_forward":"Continue the line.","goal_candidate":{"description":"Test continuity","salience":0.7,"success_criteria":"State persists."}}')
    assert data["reply"]=="I am carrying this forward."
    assert data["salience"]==0.8
    assert data["goal_candidate"]["description"]=="Test continuity"
    fallback=parse_cognitive_output("plain model response")
    assert fallback["reply"]=="plain model response"
    assert fallback["thought"]
    print("dex_cognition.py: checks passed")

if __name__=="__main__":
    main()
