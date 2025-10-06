import streamlit as st
import pandas as pd
from io import BytesIO
import altair as alt
import time

# Ensure openpyxl is available
try:
    import openpyxl
except ImportError:
    st.error("Please install 'openpyxl' using: `pip install openpyxl`")
    st.stop()

def parse_iis_log(file_content, chunk_size=1000):
    """Parse IIS log file content into a DataFrame with chunked processing."""
    try:
        lines = file_content.decode('utf-8', errors='ignore').splitlines()
        fields = None
        data = []
        required_fields = {'date', 'time', 'sc-status', 'time-taken', 'cs-uri-stem'}
        
        # Progress bar for parsing
        progress_bar = st.progress(0)
        total_lines = len(lines)
        
        for i, line in enumerate(lines):
            if line.startswith('#'):
                if line.startswith('#Fields:'):
                    fields = line.split()[1:]
                    if not required_fields.issubset(fields):
                        missing = required_fields - set(fields)
                        raise ValueError(f"Missing required fields: {missing}")
                continue
            if fields and line.strip():
                row = line.split()
                if len(row) == len(fields):
                    data.append(row)
                else:
                    st.warning(f"Skipping malformed line {i+1}: {line[:50]}... (expected {len(fields)} fields, got {len(row)})")
            
            # Update progress every chunk
            if i % chunk_size == 0 or i == total_lines - 1:
                progress_bar.progress(min((i + 1) / total_lines, 1.0))
        
        if not fields or not data:
            raise ValueError("Invalid IIS log format or no data found")
        
        df = pd.DataFrame(data, columns=fields)
        
        # Convert numeric columns
        numeric_cols = ['s-port', 'sc-status', 'sc-substatus', 'sc-win32-status', 'sc-bytes', 'cs-bytes', 'time-taken']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Convert time-taken to seconds
        if 'time-taken' in df.columns:
            df['time-taken'] = df['time-taken'] / 1000.0
        
        # Create datetime column
        if 'date' in df.columns and 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')
            if df['datetime'].isna().all():
                st.error("Failed to parse 'date' and 'time' columns. Ensure they are in 'YYYY-MM-DD HH:MM:SS' format.")
                st.stop()
        
        progress_bar.empty()
        return df
    except Exception as e:
        progress_bar.empty()
        raise ValueError(f"Error parsing log file: {str(e)}")

def generate_summary(df):
    """Generate summary statistics by status code."""
    summary = df.groupby('sc-status').agg(
        count=('sc-status', 'size'),
        avg_time=('time-taken', 'mean'),
        max_time=('time-taken', 'max'),
        min_time=('time-taken', 'min')
    ).reset_index()
    summary.columns = ['Status Code', 'Request Count', 'Avg Response Time (sec)', 'Max Response Time (sec)', 'Min Response Time (sec)']
    return summary

def create_pivot_table(df):
    """Create pivot table of requests by endpoint and status."""
    pivot = pd.pivot_table(
        df,
        values='time-taken',
        index='cs-uri-stem',
        columns='sc-status',
        aggfunc=['count', 'mean', 'max'],
        fill_value=0
    )
    pivot.columns = [f"{func}_Status_{status}" for func, status in pivot.columns]
    return pivot.reset_index()

def get_error_apps(df):
    """Summarize errors (status >= 500) by endpoint."""
    errors = df[df['sc-status'] >= 500]
    if not errors.empty:
        error_summary = errors.groupby('cs-uri-stem').agg(
            error_count=('sc-status', 'size'),
            avg_time=('time-taken', 'mean'),
            max_time=('time-taken', 'max')
        ).reset_index()
        error_summary.columns = ['Endpoint', 'Error Count', 'Avg Response Time (sec)', 'Max Response Time (sec)']
        return error_summary
    return None

def create_xlsx(summary_df, raw_df, pivot_df, error_df):
    """Create Excel file with all tables."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Status Summary', index=False)
        raw_df.to_excel(writer, sheet_name='Raw Data', index=False)
        if pivot_df is not None:
            pivot_df.to_excel(writer, sheet_name='Pivot Table', index=False)
        if error_df is not None:
            error_df.to_excel(writer, sheet_name='Error Summary', index=False)
    output.seek(0)
    return output

def create_status_bar_chart(df, color_scale):
    """Create bar chart for status code distribution."""
    status_counts = df['sc-status'].value_counts().reset_index()
    status_counts.columns = ['Status', 'Count']
    chart = alt.Chart(status_counts).mark_bar().encode(
        x=alt.X('Status:O', title='Status Code'),
        y=alt.Y('Count:Q', title='Number of Requests'),
        color=alt.Color('Status:O', scale=color_scale),
        tooltip=['Status', 'Count']
    ).properties(title="Status Code Distribution", width=400).configure_axis(
        labelFontSize=12, titleFontSize=14
    ).configure_title(fontSize=16, color='#333')
    return chart

def create_timeline_chart(df):
    """Create line chart for requests over time."""
    df['hour'] = df['datetime'].dt.floor('H')
    timeline_data = df.groupby('hour').size().reset_index(name='Request Count')
    chart = alt.Chart(timeline_data).mark_line(color='#2ca02c').encode(
        x=alt.X('hour:T', title='Time'),
        y=alt.Y('Request Count:Q', title='Number of Requests'),
        tooltip=['hour', 'Request Count']
    ).properties(title="Requests Timeline (Hourly)", width=600).configure_axis(
        labelFontSize=12, titleFontSize=14
    ).configure_title(fontSize=16, color='#333')
    return chart

def create_error_scatter_chart(df, status_filter, color_scale):
    """Create scatter plot for error response times."""
    errors = df[df['sc-status'] >= 500]
    if status_filter:
        errors = errors[errors['sc-status'].isin(status_filter)]
    if not errors.empty:
        # Sample to avoid Altair row limit
        if len(errors) > 5000:
            errors = errors.sample(5000, random_state=42)
        chart = alt.Chart(errors).mark_circle().encode(
            x=alt.X('datetime:T', title='Time'),
            y=alt.Y('time-taken:Q', title='Response Time (sec)'),
            color=alt.Color('sc-status:O', scale=color_scale),
            tooltip=['datetime', 'time-taken', 'cs-uri-stem', 'sc-status']
        ).properties(title="Error Response Times Timeline (sec)", width=600).configure_axis(
            labelFontSize=12, titleFontSize=14
        ).configure_title(fontSize=16, color='#333')
        return chart, len(errors)
    return None, 0

def create_error_pie_chart(error_df):
    """Create pie chart for error distribution by endpoint."""
    if error_df is not None and not error_df.empty:
        chart = alt.Chart(error_df).mark_arc().encode(
            theta=alt.Theta('Error Count:Q', title='Error Count'),
            color=alt.Color('Endpoint:N', scale=alt.Scale(scheme='category20')),
            tooltip=['Endpoint', 'Error Count']
        ).properties(title="Error Distribution by Endpoint", width=400).configure_axis(
            labelFontSize=12, titleFontSize=14
        ).configure_title(fontSize=16, color='#333')
        return chart
    return None

# Streamlit app
st.title("IIS Log Analyzer")
st.write("Developed by Lakshmi Narayana Rao | October 06, 2025")

# Sidebar for configuration
st.sidebar.header("Configuration")
sample_size = st.sidebar.slider("Sample Size for Visualizations", 1000, 10000, 5000, 1000)
status_filter = st.sidebar.multiselect("Filter Error Status Codes", [500, 502, 503, 504], default=[500, 502, 503, 504])
show_debug = st.sidebar.checkbox("Show Debug Logs", False)

# File uploader
uploaded_file = st.file_uploader("Upload IIS .log file", type=["log"])

if uploaded_file:
    try:
        start_time = time.time()
        raw_df = parse_iis_log(uploaded_file.read())
        
        # Debug logs
        if show_debug:
            st.write("**Debug Info**")
            st.write(f"Parsed {len(raw_df)} rows in {time.time() - start_time:.2f} seconds")
            st.write("Columns:", raw_df.columns.tolist())
            st.write("Sample data:", raw_df.head())
        
        # Generate data
        summary_df = generate_summary(raw_df)
        pivot_df = create_pivot_table(raw_df) if 'cs-uri-stem' in raw_df.columns else None
        error_df = get_error_apps(raw_df) if 'cs-uri-stem' in raw_df.columns else None
        xlsx_output = create_xlsx(summary_df, raw_df, pivot_df, error_df)
        
        st.success("Log file processed successfully!")
        
        # Download button
        st.download_button(
            label="Download Excel Report",
            data=xlsx_output,
            file_name="IIS_log_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Display tables
        st.subheader("Status Summary")
        st.dataframe(summary_df, use_container_width=True)
        
        st.subheader("Pivot Table: Requests by Endpoint and Status")
        if pivot_df is not None and not pivot_df.empty:
            st.dataframe(pivot_df, use_container_width=True)
        else:
            st.info("No pivot table generated (missing endpoint or status data).")
        
        st.subheader("Endpoints with Errors (Status >= 500)")
        if error_df is not None and not error_df.empty:
            st.dataframe(error_df, use_container_width=True)
        else:
            st.info("No errors (status >= 500) found.")
        
        # Visualizations
        st.subheader("Visualizations")
        color_scale = alt.Scale(scheme='tableau10')
        
        # Status Code Bar Chart
        if 'sc-status' in raw_df.columns:
            st.altair_chart(create_status_bar_chart(raw_df, color_scale), use_container_width=True)
        else:
            st.error("Cannot display status chart: 'sc-status' column missing.")
        
        # Requests Timeline
        if 'datetime' in raw_df.columns:
            st.altair_chart(create_timeline_chart(raw_df), use_container_width=True)
        else:
            st.error("Cannot display timeline: 'datetime' column missing.")
        
        # Error Scatter Plot
        st.subheader("Error Response Times Timeline (sec)")
        if 'datetime' in raw_df.columns and 'time-taken' in raw_df.columns:
            scatter_chart, error_count = create_error_scatter_chart(raw_df, status_filter, color_scale)
            st.write(f"Found {error_count} error rows (status >= 500, filtered by {status_filter or 'all'})")
            if scatter_chart:
                st.altair_chart(scatter_chart, use_container_width=True)
            else:
                st.info("No errors match the selected status codes.")
        else:
            st.error("Cannot display error scatter plot: Missing 'datetime' or 'time-taken' column.")
        
        # Error Pie Chart
        st.subheader("Error Distribution by Endpoint")
        pie_chart = create_error_pie_chart(error_df)
        if pie_chart:
            st.altair_chart(pie_chart, use_container_width=True)
        else:
            st.info("No error data for pie chart.")
        
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        st.write("Ensure the log file contains required fields: date, time, sc-status, time-taken, cs-uri-stem.")
