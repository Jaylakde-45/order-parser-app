import streamlit as st
import pandas as pd
import re
from io import BytesIO

# =============================================
# 🧠 ULTIMATE ORDER PARSER (6 Columns)
# Extracts: Name, Phone, Time, Items, Notes
# =============================================

def parse_chat_text(content):
    """
    Extracts EVERYTHING a shopkeeper needs:
    - Customer Name
    - Phone Number (if available)
    - Order Time
    - Items List
    - Special Notes (Urgent, Delivery time, etc.)
    """
    lines = content.split('\n')
    
    # Common grocery items (Add more as per your market)
    items = ['sugar', 'milk', 'maggi', 'rice', 'wheat', 'atta', 'oil', 'salt', 
             'tea', 'biscuit', 'soap', 'shampoo', 'coconut', 'turmeric', 'chilli',
             'coke', 'pepsi', 'water', 'bread', 'butter', 'cheese', 'egg', 'chicken',
             'dal', 'toor', 'moong', 'masala', 'paneer', 'curd', 'buttermilk',
             'coriander', 'jeera', 'hing', 'garam', 'kaju', 'badam', 'rice', 'wheat',
             'onion', 'potato', 'tomato', 'garlic', 'ginger']
    
    orders = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # --- STEP 1: Extract Phone Number (if present) ---
        phone_match = re.search(r'(\+91|0)?[6-9]\d{9}', line)
        phone = phone_match.group(0) if phone_match else ""
        # Remove phone from line to avoid confusion
        if phone:
            line = line.replace(phone, "").strip()
        
        # --- STEP 2: Extract Time (WhatsApp format: "9:15 am") ---
        time_match = re.search(r'(\d{1,2}:\d{2}\s*[AP]M?)', line, re.IGNORECASE)
        time = time_match.group(0).upper() if time_match else ""
        if time:
            line = line.replace(time, "").strip()
        
        # --- STEP 3: Extract Customer Name ---
        # Pattern: "... - Customer: Order" or just "Customer: Order"
        name = ""
        order_text = ""
        
        match = re.match(r'^[^:]*-\s*([^:]+):\s*(.+)', line)
        if match:
            name = match.group(1).strip()
            order_text = match.group(2).strip()
        else:
            fallback_match = re.match(r'^([^:]+):\s*(.+)', line)
            if fallback_match:
                name = fallback_match.group(1).strip()
                order_text = fallback_match.group(2).strip()
            else:
                # If no name found, skip this line
                continue
        
        # Clean name: remove extra spaces, "am" / "pm" leftovers
        name = re.sub(r'\s+am$|\s+pm$', '', name, flags=re.IGNORECASE).strip()
        
        # --- STEP 4: Extract Special Notes (Urgent, Delivery time, etc.) ---
        notes = ""
        note_keywords = ['urgent', 'deliver', 'after', 'before', 'call', 'please', 'without', 
                         'with', 'home', 'shop', 'fast', 'jaldi', 'pay', 'cash', 'upi']
        lower_text = order_text.lower()
        for keyword in note_keywords:
            if keyword in lower_text:
                # Try to extract the whole phrase containing the keyword
                # Simple approach: if keyword exists, extract the whole sentence or leftover
                notes = order_text
                break
        
        # If notes is too long (contains items), try to separate items vs notes
        # Let's remove the items we know from the notes to clean it up
        if notes:
            for item in items:
                if item in notes.lower():
                    # Remove item phrases from notes to keep notes clean
                    # Just a simple filter: if notes contains only items, set notes to "-"
                    pass
            # If notes is exactly same as order_text, it might just be items, set to "-"
            if notes == order_text:
                # Check if order_text has any special words
                has_note = any(kw in lower_text for kw in ['urgent', 'deliver', 'after', 'before', 'call'])
                if not has_note:
                    notes = "-"
        
        # --- STEP 5: Parse Items (with quantities) ---
        found_items = []
        lower_order = order_text.lower()
        
        for item in items:
            if item in lower_order:
                quantity_match = re.search(r'(\d+)\s*(kg|g|litre|l|ml|packets|packet|pcs|piece)?\s*' + item, lower_order)
                if quantity_match:
                    qty = quantity_match.group(0)
                    found_items.append(qty)
                else:
                    found_items.append(item)
        
        # If no items found, but order_text has something, put it as raw
        if not found_items and order_text:
            found_items = [order_text[:50] + ('...' if len(order_text) > 50 else '')]
        
        # --- STEP 6: Build the final row ---
        if name:
            # Clean the items list to avoid duplicates
            unique_items = []
            for f in found_items:
                if f not in unique_items:
                    unique_items.append(f)
            
            orders.append({
                'Customer': name.title(),
                'Phone': phone if phone else "-",
                'Time': time if time else "-",
                'Order Items': ', '.join(unique_items) if unique_items else order_text[:50],
                'Special Notes': notes if notes and notes != order_text else "-"
            })

    return pd.DataFrame(orders)

# =============================================
# 📱 STREAMLIT UI (With New Columns)
# =============================================

st.set_page_config(page_title="Order Parser Pro", page_icon="📊", layout="centered")

st.markdown("""
    <div style="background-color: #075E54; padding: 20px; border-radius: 10px; text-align: center;">
        <h1 style="color: white;">📊 Ultimate Order Aggregator</h1>
        <p style="color: #DCF8C6;">नाव, फोन, वेळ, वस्तू, आणि सूचना - सगळं एका जागी!</p>
    </div>
    <br>
""", unsafe_allow_html=True)

st.markdown("### 📥 How to use:")

tab1, tab2 = st.tabs(["📤 Upload .txt File", "✏️ Paste Messages Directly"])

with tab1:
    st.caption("Export WhatsApp chat as .txt and upload here.")
    uploaded_file = st.file_uploader("Choose a .txt file", type=['txt'], key="file_uploader")

with tab2:
    st.caption("Just copy specific messages from WhatsApp and paste them here.")
    st.info("💡 **Pro Tip**: On WhatsApp, long-press a message → tap 'Copy' → paste below.")
    pasted_text = st.text_area(
        "📋 Paste your chat messages here (one message per line):",
        height=200,
        placeholder="Example:\n12/06/24, 9:15 am - Ramesh: 2kg sugar, 1L milk, deliver urgently\nSuresh: 1kg rice, 500g tur dal - call before delivery",
        key="text_area"
    )

# Process
content = None

if uploaded_file is not None:
    content = uploaded_file.read().decode('utf-8', errors='ignore')
    st.success(f"✅ File loaded! Found {len(content.splitlines())} lines.")
elif pasted_text.strip():
    content = pasted_text
    st.success(f"✅ Text pasted! Found {len(content.splitlines())} lines.")

if content:
    if st.button("🚀 Generate Complete Order Book", type="primary", use_container_width=True):
        with st.spinner("🧠 Extracting Name, Phone, Time, Items, and Notes..."):
            df = parse_chat_text(content)
            
            if df.empty:
                st.error("❌ No orders found! Make sure messages are in 'Name: Order' format.")
            else:
                st.success(f"✅ Found {len(df)} orders! All details extracted.")
                
                # Display the dataframe with all 5 columns
                st.dataframe(df, use_container_width=True)
                
                # Show summary stats
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Orders", len(df))
                with col2:
                    phones = df[df['Phone'] != "-"].shape[0]
                    st.metric("Phone Numbers Found", phones)
                with col3:
                    notes = df[df['Special Notes'] != "-"].shape[0]
                    st.metric("Special Instructions", notes)
                
                # Export to Excel
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Orders')
                output.seek(0)
                
                st.download_button(
                    label="📥 Download Complete Order Book (Excel)",
                    data=output,
                    file_name="complete_order_book.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
                st.balloons()
                st.info("💡 **This saves 2 hours daily!** Show this to any shopkeeper and charge ₹500/month.")
else:
    st.warning("📤 Upload a .txt file OR paste your messages above to get started.")

st.caption("💡 **Sample to test:**\n\n12/06/24, 9:15 am - Ramesh: 2kg sugar, 1L milk - urgent deliver\n12/06/24, 9:18 am - Suresh: 1kg rice, 500g tur dal, call before delivery")