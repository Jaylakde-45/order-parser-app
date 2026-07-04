import streamlit as st
import pandas as pd
import re
import matplotlib.pyplot as plt
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, firestore
import time
import datetime
from fpdf import FPDF

# =============================================
# 🧠 PARSE SINGLE ORDER
# =============================================

def parse_single_order_line(line):
    """
    Parses a single WhatsApp order line and extracts:
    Customer, Items, Phone, Amount, Notes
    """
    line = line.strip()
    if not line:
        return None
    
    # --- STEP 1: Extract Phone Number (if present) ---
    phone = ""
    phone_match = re.search(r'(\+91|0)?[6-9]\d{9}', line)
    if phone_match:
        phone = phone_match.group(0)
        line = line.replace(phone, "").strip()
    
    # --- STEP 2: Remove Date/Time ---
    date_time_pattern = r'^[\d/,\s:]+[AP]M?\s*-\s*'
    line = re.sub(date_time_pattern, '', line, flags=re.IGNORECASE)
    line = re.sub(r'\d{1,2}:\d{2}\s*[AP]M?\s*', '', line, flags=re.IGNORECASE)
    line = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4}\s*', '', line)
    
    # --- STEP 3: Extract Name and Order Text ---
    name = ""
    order_text = ""
    
    fallback_match = re.match(r'^([^:]+):\s*(.+)', line)
    if fallback_match:
        name = fallback_match.group(1).strip()
        order_text = fallback_match.group(2).strip()
    else:
        parts = line.split(' ', 1)
        if len(parts) >= 2:
            name = parts[0].strip()
            order_text = parts[1].strip()
        else:
            return None
    
    name = re.sub(r'\s+am$|\s+pm$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+AM$|\s+PM$', '', name).strip()
    
    if not name or re.match(r'^[\d/,\s]+$', name):
        return None
    
    # --- STEP 4: Extract Amount (₹) ---
    amount = 0
    amount_match = re.search(r'[₹]\s*(\d+)|Rs\.?\s*(\d+)|rupees\s*(\d+)|(\d+)\s*(?:rs|₹|rupees)', order_text, re.IGNORECASE)
    if amount_match:
        for group in amount_match.groups():
            if group is not None:
                amount = int(group)
                break
        order_text = re.sub(r'[₹]\s*\d+|Rs\.?\s*\d+|rupees\s*\d+|\d+\s*(?:rs|₹|rupees)', '', order_text, flags=re.IGNORECASE).strip()
    
    # --- STEP 5: Extract Notes ---
    notes = ""
    note_keywords = ['urgent', 'deliver', 'after', 'before', 'call', 'please', 'jaldi', 'cash', 'home', 'shop']
    lower_text = order_text.lower()
    
    for keyword in note_keywords:
        if keyword in lower_text:
            note_pattern = r'\s*[-–—]\s*(.*)$'
            note_match = re.search(note_pattern, order_text)
            if note_match:
                notes = note_match.group(1).strip()
                order_text = re.sub(note_pattern, '', order_text).strip()
            else:
                notes = keyword
                order_text = re.sub(r'\s*' + keyword + r'\s*', '', order_text, flags=re.IGNORECASE).strip()
            break
    
    # --- STEP 6: Clean up ---
    order_text = re.sub(r',\s*,', ',', order_text)
    order_text = re.sub(r'\s*,\s*$', '', order_text)
    order_text = re.sub(r'\s+and\s+', ', ', order_text)
    order_text = re.sub(r'\s+', ' ', order_text).strip()
    
    if not order_text:
        order_text = "No items specified"
    
    return {
        'customer': name.title(),
        'phone': phone if phone else "",
        'items': order_text,
        'amount': amount,
        'notes': notes if notes else ""
    }

# =============================================
# 🚀 OAI DASHBOARD
# =============================================

st.set_page_config(page_title="OAI Dashboard", page_icon="📊", layout="wide")

# --- FIREBASE SETUP ---
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase_credentials.json")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"❌ Firebase error: {e}. Please place firebase_credentials.json in the project folder.")
        st.stop()

db = firestore.client()

# =============================================
# 📊 HELPER FUNCTIONS
# =============================================

def save_order_to_firebase(customer, items, amount, phone="", notes=""):
    try:
        db.collection('orders').add({
            'customer': customer,
            'phone': phone,
            'items': items,
            'amount': float(amount) if amount else 0,
            'notes': notes,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'date': time.strftime("%Y-%m-%d")
        })
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def load_orders_from_firebase():
    try:
        docs = db.collection('orders').order_by('timestamp', direction=firestore.Query.DESCENDING).get()
        orders = []
        for doc in docs:
            data = doc.to_dict()
            orders.append({
                'Customer': data.get('customer', 'Unknown'),
                'Phone': data.get('phone', '-'),
                'Time': data.get('timestamp', '').strftime("%I:%M %p") if data.get('timestamp') else '-',
                'Order Items': data.get('items', ''),
                'Special Notes': data.get('notes', '-'),
                'Total (₹)': data.get('amount', 0)
            })
        return pd.DataFrame(orders)
    except Exception as e:
        st.error(f"Error loading: {e}")
        return pd.DataFrame()

def predict_stock(df):
    all_items = []
    for items_str in df['Order Items']:
        if items_str == "-" or pd.isna(items_str):
            continue
        parts = items_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            match = re.match(r'(\d+\.?\d*)\s*(kg|g|litre|l|ml|packets|packet|pcs|piece|kgs)?\s*(.+)', part, re.IGNORECASE)
            if match:
                quantity = float(match.group(1))
                unit = match.group(2).lower() if match.group(2) else ""
                item_name = match.group(3).strip().lower()
                if unit in ['g', 'gm', 'grams']:
                    quantity = quantity / 1000
                    unit = 'kg'
                elif unit in ['litre', 'l']:
                    unit = 'L'
                elif unit in ['packets', 'packet']:
                    unit = 'packets'
                elif unit in ['pcs', 'piece']:
                    unit = 'pcs'
                else:
                    unit = 'kg' if unit else 'units'
                all_items.append({'item': item_name, 'qty': quantity, 'unit': unit})
            else:
                all_items.append({'item': part, 'qty': 1, 'unit': 'units'})
    
    if not all_items:
        return pd.DataFrame()
    
    items_df = pd.DataFrame(all_items)
    summary = items_df.groupby('item').agg({
        'qty': 'sum',
        'unit': lambda x: x.mode()[0] if not x.mode().empty else 'units'
    }).reset_index()
    summary.columns = ['Item', 'Total Sold (7 Days)', 'Unit']
    days = 7
    summary['Avg Daily'] = (summary['Total Sold (7 Days)'] / days).round(2)
    summary['Predicted Next Week'] = (summary['Avg Daily'] * days).round(0)
    summary['Recommended Order (+10%)'] = (summary['Predicted Next Week'] * 1.1).round(0)
    summary = summary.sort_values('Total Sold (7 Days)', ascending=False)
    return summary

# =============================================
# 📄 PDF GENERATOR
# =============================================

def generate_pdf_report(df, shop_name="My Shop"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"📊 Weekly Report - {shop_name}", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Date: {datetime.datetime.now().strftime('%d-%b-%Y')}", ln=True, align='C')
    pdf.ln(10)
    
    total_orders = len(df)
    total_rev = pd.to_numeric(df['Total (₹)'], errors='coerce').sum()
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(100, 10, txt=f"Total Orders: {total_orders}", ln=False)
    pdf.cell(100, 10, txt=f"Total Revenue: ₹{total_rev}", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Top 5 Selling Items", ln=True)
    pdf.set_font("Arial", '', 12)
    
    all_items = []
    for items_str in df['Order Items']:
        if items_str != "-" and not pd.isna(items_str):
            for item in items_str.split(','):
                clean_item = item.strip()
                if clean_item:
                    cleaned_name = re.sub(r'^[\d\.]+\s*(kg|g|litre|l|ml|packets|packet|pcs|piece|kgs)?\s*', '', clean_item, flags=re.IGNORECASE)
                    cleaned_name = cleaned_name.strip()
                    if cleaned_name:
                        all_items.append(cleaned_name)
    
    if all_items:
        item_counts = pd.Series(all_items).value_counts().head(5)
        for idx, (item, count) in enumerate(item_counts.items(), 1):
            pdf.cell(200, 10, txt=f"{idx}. {item} - {count} orders", ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="🔮 Next Week Stock Prediction", ln=True)
    pdf.set_font("Arial", '', 10)
    
    prediction_df = predict_stock(df)
    if not prediction_df.empty:
        for _, row in prediction_df.head(8).iterrows():
            pdf.cell(200, 8, txt=f"{row['Item']}: Order {row['Recommended Order (+10%)']} {row['Unit']}", ln=True)
    
    pdf.ln(20)
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(200, 10, txt="Generated by OAI Dashboard | ₹2,000/month | 7 Days Free Trial", ln=True, align='C')
    
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return pdf_bytes

# =============================================
# 📱 STREAMLIT UI
# =============================================

st.markdown("""
    <div style="background-color: #075E54; padding: 20px; border-radius: 10px; text-align: center;">
        <h1 style="color: white;">📊 Order Analytics Intelligence (OAI)</h1>
        <p style="color: #DCF8C6;">Record Orders • Auto-Report • Stock Prediction</p>
    </div>
    <br>
""", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📝 Add Order", "📋 Today's Orders", "📈 Weekly Report"])

# =============================================
# TAB 1: ADD ORDER
# =============================================
with tab1:
    st.markdown("### 📝 Record New Order")
    
    col1, col2 = st.columns(2)
    with col1:
        customer = st.text_input("👤 Customer Name")
        items = st.text_area("🛒 Order Items", placeholder="2kg sugar, 1L milk")
    with col2:
        phone = st.text_input("📞 Phone (optional)")
        amount = st.text_input("💰 Total Amount (₹)")
        notes = st.text_input("📝 Special Notes")
    
    if st.button("💾 Save Order", use_container_width=True, type="primary"):
        if customer and items:
            with st.spinner("Saving..."):
                if save_order_to_firebase(customer, items, amount, phone, notes):
                    st.success("✅ Saved!")
                    st.balloons()
                else:
                    st.error("❌ Failed.")
        else:
            st.warning("Enter Name and Items.")
    
    st.markdown("---")
    st.markdown("### 📥 Or Paste WhatsApp Order Message")
    st.caption("Paste the exact message you received on WhatsApp. The app will auto-fill everything!")
    
    raw_message = st.text_area("📋 Paste Order Here", height=100, placeholder="12/06/24, 9:15 am - Ramesh: 2kg sugar, 1L milk ₹60 - urgent")
    
    if st.button("🔍 Parse & Save Order", use_container_width=True):
        if raw_message:
            with st.spinner("Parsing..."):
                parsed = parse_single_order_line(raw_message)
                if parsed:
                    st.success("✅ Parsed successfully!")
                    st.json(parsed)
                    if save_order_to_firebase(parsed['customer'], parsed['items'], parsed['amount'], parsed['phone'], parsed['notes']):
                        st.success("✅ Order saved to cloud!")
                        st.balloons()
                    else:
                        st.error("❌ Failed to save.")
                else:
                    st.error("❌ Could not parse. Make sure it's in 'Name: Order' format.")
        else:
            st.warning("Please paste a message.")

# =============================================
# TAB 2: TODAY'S ORDERS
# =============================================
with tab2:
    st.markdown("### 📋 Saved Orders")
    if st.button("🔄 Refresh", use_container_width=True):
        with st.spinner("Loading..."):
            df = load_orders_from_firebase()
            if not df.empty:
                st.session_state.df = df
                st.success(f"✅ Loaded {len(df)} orders!")
                st.dataframe(df, use_container_width=True)
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Orders')
                output.seek(0)
                st.download_button("📥 Download Excel", data=output, file_name="orders.xlsx")
            else:
                st.warning("No orders found.")
    
    if 'df' in st.session_state:
        st.dataframe(st.session_state.df, use_container_width=True)

# =============================================
# TAB 3: WEEKLY REPORT
# =============================================
with tab3:
    st.markdown("### 📈 Weekly Report & Stock Prediction")
    
    if 'df' not in st.session_state or st.session_state.df is None:
        with st.spinner("Loading..."):
            st.session_state.df = load_orders_from_firebase()
    
    if st.session_state.df is not None and not st.session_state.df.empty:
        df = st.session_state.df
        total_rev = pd.to_numeric(df['Total (₹)'], errors='coerce').sum()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📦 Total Orders", len(df))
        with col2:
            st.metric("💰 Total Revenue", f"₹{total_rev}")
        with col3:
            avg_order = total_rev / len(df) if len(df) > 0 else 0
            st.metric("📊 Avg Order Value", f"₹{round(avg_order, 2)}")
        
        st.markdown("---")
        
        # Top Items Chart
        st.markdown("#### 🏆 Top 5 Selling Items")
        all_items = []
        for items_str in df['Order Items']:
            if items_str != "-" and not pd.isna(items_str):
                for item in items_str.split(','):
                    clean_item = item.strip()
                    if clean_item:
                        cleaned_name = re.sub(r'^[\d\.]+\s*(kg|g|litre|l|ml|packets|packet|pcs|piece|kgs)?\s*', '', clean_item, flags=re.IGNORECASE)
                        cleaned_name = cleaned_name.strip()
                        if cleaned_name:
                            all_items.append(cleaned_name)
        
        if all_items:
            item_counts = pd.Series(all_items).value_counts().head(5)
            fig, ax = plt.subplots(figsize=(6, 4))
            item_counts.plot(kind='bar', ax=ax, color='#075E54')
            ax.set_title("Top 5 Most Ordered Items (Frequency)", fontsize=14)
            ax.set_xlabel("Item")
            ax.set_ylabel("Number of Orders")
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            st.pyplot(fig)
        else:
            st.info("No item data available.")
        
        # Top Customers
        st.markdown("#### 🧑‍🤝‍🧑 Top 5 Customers")
        customer_counts = df['Customer'].value_counts().head(5)
        st.dataframe(pd.DataFrame({
            'Customer': customer_counts.index,
            'Orders': customer_counts.values
        }), use_container_width=True)
        
        st.markdown("---")
        
        # Stock Prediction
        st.markdown("#### 🔮 Next Week Stock Prediction")
        prediction_df = predict_stock(df)
        if not prediction_df.empty:
            display_df = prediction_df.head(10).copy()
            display_df.columns = ['Item', 'Total Sold (7 Days)', 'Unit', 'Avg Daily', 'Predicted Next Week', 'Recommended Order (+10%)']
            st.dataframe(display_df, use_container_width=True)
            
            pred_output = BytesIO()
            with pd.ExcelWriter(pred_output, engine='openpyxl') as writer:
                prediction_df.to_excel(writer, index=False, sheet_name='Stock_Prediction')
            pred_output.seek(0)
            st.download_button("📥 Download Stock Prediction", data=pred_output, file_name="stock_prediction.xlsx")
        else:
            st.warning("Not enough data.")
        
        st.markdown("---")
        
        # PDF Download (Only)
        st.markdown("#### 📤 Download Report")
        if st.button("📄 Download PDF Report", use_container_width=True):
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_pdf_report(df, shop_name="Kankavli Store")
                st.download_button(
                    label="📥 Click to Download PDF",
                    data=pdf_bytes,
                    file_name=f"weekly_report_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        
        st.download_button(
            label="📥 Download Full Report (CSV)",
            data=df.to_csv(index=False),
            file_name="full_report.csv",
            use_container_width=True
        )
        
    else:
        st.warning("⚠️ No orders found. Go to 'Add Order' tab and record some orders.")

st.caption("💡 **₹2,000/month** | 7 Days Free Trial | Kankavli's #1 Order System")
