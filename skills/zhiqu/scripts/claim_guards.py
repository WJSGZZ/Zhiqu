"""Bounded language checks for claims about a reader's personal probability."""
import re

SECOND_PERSON=re.compile(r'你|您')
PROBABILITY_WORD=re.compile(r'机会|概率|把握|可能(?:性)?')
PROPORTION=re.compile(r'\d+(?:\.\d+)?\s*[%％]|[零〇一二两三四五六七八九十百\d]+(?:点[零一二三四五六七八九\d]+)?\s*成|[零〇一二两三四五六七八九十百\d]+分之[零〇一二两三四五六七八九十百\d]+|一半|过半|半数|(?<![\d.])0\.\d+(?![\d.])')
DENIED_PERSONAL=re.compile(r'(?:不是|并非|不等于|不代表|不意味着|不能(?:据此)?(?:被)?(?:解释为|理解为|视为|当作|作为|换算为|推算为|说)|不可(?:理解为|解释为|视为|当作|换算为|推算为)|不应(?:理解为|解释为|视为|当作|换算为|推算为)|无法(?:计算|推算|确定|估算)).{0,24}(?:你|您|个人).{0,20}(?:概率|机会|可能|把握)')

def personal_probability_errors(text,location=''):
    errors=[]
    for sentence in re.split(r'[。！？!?；;\n]',str(text)):
        # Denial applies to its own clause. A denial elsewhere cannot excuse a
        # separate affirmative “你有八成机会” in the same sentence.
        affirmative='，'.join(clause for clause in re.split(r'[，,]',sentence) if not DENIED_PERSONAL.search(clause))
        affirmative=re.sub(r'(?:你|您)(?:需要|须|应当|应|要)?(?:核对|核实|查阅|检查|研究)(?:该|这个|这一)?(?=群体)', '', affirmative)
        if SECOND_PERSON.search(affirmative) and PROBABILITY_WORD.search(affirmative) and PROPORTION.search(affirmative):
            errors.append(location+'：禁止把比例写成第二人称个人概率：'+affirmative.strip())
    return errors
