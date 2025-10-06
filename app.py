import streamlit as st
import pandas as pd
from io import BytesIO
import altair as alt

# Ensure openpyxl is available
try:
    import openpyxl
except ImportError:
    st.error("The 'openpyxl' library is not installed. Please install it using: `pip install openpyxl`")
    st.stop()

def parse_iis_log(file_content):
    """Parse IIS log file content into a pandas DataFrame."""
    try:
        lines = file_content.decode('utf-8', errors='ignore').splitlines()
        fields = None
        data = []
        
        for line in lines:
            if line.startswith('#'):
                if line.startswith('#Fields:'):
                    fields = line.split()[1:]  # Extract field names
                continue
            if fields and line.strip():
                row = line.split()
                if len(row) == len(fields):
                    data.append(row)
                else:
                    st.warning(f"Skipping malformed line: {line[:50]}... (expected {len(fields)} fields, got {len(row)})")
        
        if not fields or not data:
            raise ValueError("Invalid IIS log format or no data found")
        
        df = pd.DataFrame(data, columns=fields)
        
        # Convert relevant columns to numeric
        numeric_cols = ['s-port', 'sc-status', 'sc-substatus', 'sc-win32-status', 'sc-bytes', 'cs-bytes', 'time-taken']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Convert time-taken from milliseconds to seconds
        if 'time-taken' in df.columns:
            df['time-taken'] = df['time-taken'] / 1000.0  # Convert ms to seconds
        
        # Combine date and time into datetime
        if 'date' in df.columns and 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')
            if df['datetime'].isna().all():
                st.warning("Failed to parse 'date' and 'time' columns into 'datetime'. Check log file format.")
        
        return df
    except Exception as e:
        raise ValueError(f"Error parsing log file: {str(e)}")

def generate_summary(df):
    """Generate summary statistics by status code."""
    try:
        if 'sc-status' not in df.columns or 'time-taken' not in df.columns:
            raise ValueError("Required columns 'sc-status' or 'time-taken' not found")
        
        summary = df.groupby('sc-status').agg(
            count=('sc-status', 'size'),
            avg_time_taken=('time-taken', 'mean'),
            max_time_taken=('time-taken', 'max'),
            min_time_taken=('time-taken', 'min')
        ).reset_index()
        
        summary.columns = ['Status Code', 'Request Count', 'Avg Response Time (sec)', 'Max Response Time (sec)', 'Min Response Time (sec)']
        return summary
    except Exception as e:
        raise ValueError(f"Error generating summary: {str(e)}")

def create_pivot_table(df):
    """Create a pivot table of requests by endpoint and status."""
    try:
        if 'sc-status' in df.columns and 'cs-uri-stem' in df.columns:
            pivot = pd.pivot_table(
                df,
                values='time-taken',
                index='cs-uri-stem',
                columns='sc-status',
                aggfunc=['count', 'mean', 'max'],
                fill_value=0
            )
            pivot.columns = ['_'.join(map(str, col)).replace('mean', 'Avg Time (sec)').replace('max', 'Max Time (sec)') for col in pivot.columns]
            return pivot.reset_index()
        return None
    except Exception as e:
        st.warning(f"Error creating pivot table: {str(e)}")
        return None

def get_error_apps(df):
    """Summarize errors (status >= 500) by endpoint."""
    try:
        if 'sc-status' in df.columns and 'cs-uri-stem' in df.columns:
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
    except Exception as e:
        st.warning(f"Error generating error summary: {str(e)}")
        return None

def create_xlsx(summary_df, raw_df, pivot_df=None, error_df=None):
    """Create an Excel file with summary, raw data, pivot table, and error summary."""
    try:
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
    except Exception as e:
        raise ValueError(f"Error creating XLSX file: {str(e)}")

# Streamlit app
st.title("IIS Log Analyzer with Visualizations")

# Developer and Hosted Date
st.markdown("""
    <div style='text-align: center; padding: 10px;'>
        <p>Developed by: <b>Lakshmi Narayana Rao</b></p>
        <p>Hosted on: <b>October 06, 2025</b></p>
    </div>
""", unsafe_allow_html=True)

# File uploader
uploaded_file = st.file_uploader("Upload IIS .log file", type=["log"])

if uploaded_file:
    try:
        # Parse log file
        file_content = uploaded_file.read()
        raw_df = parse_iis_log(file_content)
        st.write("Columns in parsed log data:", raw_df.columns.tolist())
        
        # Generate summaries and tables
        summary_df = generate_summary(raw_df)
        pivot_df = create_pivot_table(raw_df)
        error_df = get_error_apps(raw_df)
        
        # Create Excel file
        xlsx_output = create_xlsx(summary_df, raw_df, pivot_df, error_df)
        
        st.success("Log file processed successfully!")
        
        # Download button
        st.download_button(
            label="Download Excel Report",
            data=xlsx_output,
            file_name="IIS_log_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Display Pivot Table
        st.subheader("Pivot Table: Requests by Endpoint and Status")
        if pivot_df is not None and not pivot_df.empty:
            st.dataframe(pivot_df, use_container_width=True)
        else:
            st.info("No pivot table generated (missing required columns or data).")
        
        # Display Error Summary
        st.subheader("Endpoints with Errors (Status >= 500)")
        if error_df is not None and not error_df.empty:
            st.dataframe(error_df, use_container_width=True)
        else:
            st.info("No errors (status >= 500) found in the log.")
        
        # Visualizations
        st.subheader("Visualizations")
        color_scale = alt.Scale(domain=['200', '500'], range=['#1f77b4', '#ff3333'])  # Blue for 200, red for 500
        
        # Bar Chart: Status Code Counts
        if 'sc-status' in raw_df.columns:
            status_counts = raw_df['sc-status'].value_counts().reset_index()
            status_counts.columns = ['Status', 'Count']
            bar_chart = alt.Chart(status_counts).mark_bar().encode(
                x=alt.X('Status:O', title='Status Code'),
                y=alt.Y('Count:Q', title='Number of Requests'),
                color=alt.Color('Status:O', scale=color_scale),
                tooltip=['Status', 'Count']
            ).properties(title="Status Code Distribution", width=400).configure_axis(
                labelFontSize=12, titleFontSize=14
            ).configure_title(fontSize=16, color='#333')
            st.altair_chart(bar_chart, use_container_width=True)
        else:
            st.warning("Cannot display status code distribution: 'sc-status' column missing.")
        
        # Timeline: Requests Over Time
        if 'datetime' in raw_df.columns:
            raw_df['hour'] = raw_df['datetime'].dt.floor('H')
            timeline_data = raw_df.groupby('hour').size().reset_index(name='Request Count')
            line_chart = alt.Chart(timeline_data).mark_line(color='#2ca02c').encode(
                x=alt.X('hour:T', title='Time'),
                y=alt.Y('Request Count:Q', title='Number of Requests'),
                tooltip=['hour', 'Request Count']
            ).properties(title="Requests Timeline (Hourly)", width=600).configure_axis(
                labelFontSize=12, titleFontSize=14
            ).configure_title(fontSize=16, color='#333')
            st.altair_chart(line_chart, use_container_width=True)
        else:
            st.warning("Cannot display requests timeline: 'datetime' column missing.")
        
        # Scatter Plot: Error Response Times
        st.subheader("Error Response Times Timeline (sec)")
        if 'datetime' in raw_df.columns and 'time-taken' in raw_df.columns:
            errors = raw_df[raw_df['sc-status'] >= 500]
            st.write(f"Number of error rows (status >= 500): {len(errors)}")
            if not errors.empty:
                scatter = alt.Chart(errors).mark_circle().encode(
                    x=alt.X('datetime:T', title='Time'),
                    y=alt.Y('time-taken:Q', title='Response Time (sec)'),
                    color=alt.Color('sc-status:O', scale=color_scale),
                    tooltip=['datetime', 'time-taken', 'cs-uri-stem', 'sc-status']
                ).properties(title="Error Response Times Timeline (sec)", width=600).configure_axis(
                    labelFontSize=12, titleFontSize=14
                ).configure_title(fontSize=16, color='#333')
                st.altair_chart(scatter, use_container_width=True)
            else:
                st.info("No errors (status >= 500) found in the log file. The scatter plot will not be displayed.")
        else:
            st.error("Cannot display error response times: Missing 'datetime' or 'time-taken' column.")
        
        # Preview Sections
        st.subheader("Status Summary Preview")
        st.dataframe(summary_df, use_container_width=True)
        
        st.subheader("Raw Data Preview (First 50 Error Rows, Status >= 500)")
        if 'sc-status' in raw_df.columns:
            error_rows = raw_df[raw_df['sc-status'] >= 500].head(50)
            if not error_rows.empty:
                st.dataframe(error_rows, use_container_width=True)
            else:
                st.info("No error rows (status >= 500) found in the log.")
        else:
            st.error("Cannot display error rows: 'sc-status' column missing.")
        
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        st.write("Please ensure the log file contains the required fields (e.g., date, time, sc-status, time-taken, cs-uri-stem).")
