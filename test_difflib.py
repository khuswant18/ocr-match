import difflib
import re

def clean_desc(text):
    text = text.lower()
    text = re.sub(r'\bldld\b', '', text)
    text = re.sub(r'\bvirginia\b', '', text)
    text = text.replace('prm', 'premium')
    text = text.replace('hdog', 'hotdog')
    text = text.replace('rg', 'regular')
    text = text.replace('jmb', 'jumbo')
    return text.strip()

po_desc = {
    clean_desc("virginia prm hdog rg ldld 1kg"): "2751",
    clean_desc("virginia prm hdog jmb ldld 1kg"): "2753",
    clean_desc("champion hotdog jumbo 42k/5"): "2738",
    clean_desc("champion hotdog regular 2k 5"): "2740"
}

print(po_desc)
    
inv_desc1 = clean_desc("happy booster hotdog regular 2k (premium hotdog/5")
inv_desc2 = clean_desc("happy booster hotdog jumbo 4.52k(premium hotdog/5")

print("rg match:", difflib.get_close_matches(inv_desc1, po_desc.keys(), n=1, cutoff=0.3))
print("jmb match:", difflib.get_close_matches(inv_desc2, po_desc.keys(), n=1, cutoff=0.3))

