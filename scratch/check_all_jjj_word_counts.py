import sys
sys.path.insert(0, ".")
from server.services.h3_prompt_builder import H3PromptBuilder
from scratch.test_jjj_parser import parse_jjj_prompts

prompts = parse_jjj_prompts()
for ep, shots in sorted(prompts.items()):
    for s, p in sorted(shots.items()):
        wc = H3PromptBuilder._english_word_count(p)
        print(f"Ep {ep} Shot {s} word count: {wc}")
