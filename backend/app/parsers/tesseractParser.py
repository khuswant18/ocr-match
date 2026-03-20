import re
import requests
from app.config import BACKEND_URL

def get_invoice_number(lines):
    invoice_number = ''
    for line in lines:
        if any(kw in line.lower() for kw in ('invoice no', 'inv no', 'bill no')):
            words = line.split()
            for i, word in enumerate(words):
                if any(kw in word.lower() for kw in ('no', 'no.')) and i + 1 < len(words):
                    potential_num = words[i+1]
                    if any(c.isdigit() for c in potential_num):
                        return potential_num
    return invoice_number

def get_invoice_date(lines):
    invoice_date = ''
    date_pattern = re.compile(r"\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}")
    for line in lines:
        if any(kw in line.lower() for kw in ('date', 'dt.', 'invoice date', 'dated')):
            match = date_pattern.search(line)
            if match:
                return match.group(0)
    return invoice_date

def get_due_date(lines):
    due_date = ''
    date_pattern = re.compile(r"\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}")
    for line in lines:
        if any(kw in line.lower() for kw in ('due date', 'due dt', 'valid until')):
            match = date_pattern.search(line)
            if match:
                return match.group(0)
    return due_date

def get_total_amount(lines):
    total_amount = ''
    pattern = re.compile(r"(:rs\.|inr|₹)\s(\d{1,3}(:,\d{2,3})*(:\.\d{2}))", re.IGNORECASE)
    for line in lines:
        if any(kw in line.lower() for kw in ('total', 'grand total', 'amount', 'net amount', 'total payable')):
            match = pattern.search(line)
            if match:
                return match.group(1).replace(',', '')
    return total_amount

def get_bank(lines):
    banks = [
        'hdfc', 'icici', 'state bank of india', 'sbi', 'axis',
        'kotak', 'punjab national bank', 'pnb', 'bank of baroda', 'yes bank', 'indusind bank'
    ]
    for line in lines:
        line_lower = line.lower()
        if any(b in line_lower for b in banks):
            for b in banks:
                if b in line_lower:
                    if b == 'sbi': return 'State Bank of India'
                    if b == 'pnb': return 'Punjab National Bank'
                    return b.title() + ' Bank' if 'bank' not in b else b.title()
    return ''

def get_ifsc(lines):
    ifsc = ''
    pattern = re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b')
    for line in lines:
        if 'ifsc' in line.lower() or 'rtgs' in line.lower() or 'neft' in line.lower():
            match = pattern.search(line.upper())
            if match:
                return match.group()
    return ifsc

def get_account_number(lines):
    account_number = ''
    pattern = re.compile(r'\b\d{9,18}\b')
    for line in lines:
        if any(kw in line.lower() for kw in ('a/c', 'ac no', 'account no', 'account number')):
            match = pattern.search(line)
            if match:
                return match.group()
    return account_number

def get_tin(lines, type='supplier'):
    tin = ''
    pattern = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b")
    found_tins = []
    
    for line in lines:
        matches = pattern.findall(line.upper())
        for match in matches:
            found_tins.append(match)
            
    if found_tins:
        if type == 'supplier':
            return found_tins[0]
        elif type == 'buyer' and len(found_tins) > 1:
            return found_tins[1]
    return tin

def parse_text(text):
    lines = text.split('\n')

    supplier_tin = get_tin(lines, 'supplier')
    buyer_tin = get_tin(lines, 'buyer')

    data = {
        'invoice_number': get_invoice_number(lines),
        'invoice_date': get_invoice_date(lines),
        'due_date': get_due_date(lines),
        'total_amount': get_total_amount(lines),
        'bank': get_bank(lines),
        'ifsc': get_ifsc(lines),
        'account_number': get_account_number(lines),
        'buyer_tin': buyer_tin,
        'supplier_tin': supplier_tin,
    }
    return data
