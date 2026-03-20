import re
import requests
from app.config import BACKEND_URL

def get_invoice_number(words):
    invoice_number = ''
    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in ('invoice', 'inv.', 'inv no', 'invoice no', 'bill no')):
            parts = word.split()
            for part in parts:
                if any(c.isdigit() for c in part):
                    return part
            if i + 1 < len(words):
                next_word = words[i + 1]
                if any(c.isdigit() for c in next_word):
                    return next_word
    return invoice_number

def get_invoice_date(words):
    invoice_date = ''
    date_pattern = re.compile(r"\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}")

    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in ('date', 'dt.', 'invoice date', 'dated')):
            word_parts = word.split()
            for part in word_parts:     
                match = date_pattern.search(part)
                if match:
                    return match.group(0)
              
            if i + 1 < len(words):
                next_word = words[i + 1] 
                match = date_pattern.search(next_word)
                if match:
                    return match.group(0)
    return invoice_date 

def get_due_date(words): 
    due_date = ''
    date_pattern = re.compile(r"\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}")

    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in ('due date', 'due dt', 'valid until')):
            word_parts = word.split()
            for part in word_parts:
                match = date_pattern.search(part)
                if match:
                    return match.group(0)
            
            if i + 1 < len(words):
                next_word = words[i + 1]
                match = date_pattern.search(next_word)
                if match:
                    return match.group(0)
    return due_date

def get_total_amount(words):
    total_amount = ''
    # Match patterns like 1,000.00, 1000.00, etc.
    pattern = re.compile(r"(:rs\.|inr|₹)\s(\d{1,3}(:,\d{2,3})*(:\.\d{2}))", re.IGNORECASE)
    
    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in ('total', 'grand total', 'amount', 'net amount', 'total payable')):
            if i + 1 < len(words):
                next_word = words[i + 1]
                match = pattern.search(next_word)
                if match:
                    return match.group(1).replace(',', '')
    return total_amount

def get_bank(words):
    banks = [
        'hdfc', 'icici', 'state bank of india', 'sbi', 'axis',
        'kotak', 'punjab national bank', 'pnb', 'bank of baroda', 'yes bank', 'indusind bank'
    ]
    for i, word in enumerate(words):
        word_lower = word.lower()
        if any(b in word_lower for b in banks):
            for b in banks:
                if b in word_lower:
                    if b == 'sbi': return 'State Bank of India'
                    if b == 'pnb': return 'Punjab National Bank'
                    return b.title() + ' Bank' if 'bank' not in b else b.title()
    return ''

def get_ifsc(words):
    ifsc = ''
    pattern = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
    for i, word in enumerate(words):
        if 'ifsc' in word.lower() or 'rtgs' in word.lower() or 'neft' in word.lower():
            words_split = word.split()
            for part in words_split:
                if pattern.match(part.upper()):
                    return part.upper()
            if i + 1 < len(words):
                next_word = words[i + 1]
                next_word_parts = next_word.split()
                for next_part in next_word_parts:
                    if pattern.match(next_part.upper()):
                        return next_part.upper()
    return ifsc

def get_account_number(words):
    account_number = ''
    pattern = re.compile(r'\b\d{9,18}\b')
    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in ('a/c', 'ac no', 'account no', 'account number')):
            words_split = word.split()
            for part in words_split:
                match = pattern.search(part)
                if match:
                    return match.group()
            if i + 1 < len(words):
                next_word = words[i + 1]
                match = pattern.search(next_word)
                if match:
                    return match.group()
    return account_number

def get_tin(words, type='supplier'):
    tin = ''
    pattern = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b")
    found_tins = []
    
    for i, word in enumerate(words):
        match = pattern.search(word.upper())
        if match:
            found_tins.append(match.group())
            
    if found_tins:
        # Simplistic assumption: first TIN is usually supplier, second is buyer
        if type == 'supplier':
            return found_tins[0]
        elif type == 'buyer' and len(found_tins) > 1:
            return found_tins[1]
    return tin

def parse_text(text):
    words = text.split('\n')
    
    supplier_tin = get_tin(words, 'supplier')
    buyer_tin = get_tin(words, 'buyer')

    data = {
        'invoice_number': get_invoice_number(words),
        'invoice_date': get_invoice_date(words),
        'due_date': get_due_date(words),
        'total_amount': get_total_amount(words),
        'bank': get_bank(words),
        'ifsc': get_ifsc(words),
        'account_number': get_account_number(words),
        'buyer_tin': buyer_tin,
        'supplier_tin': supplier_tin,
    }
    return data
