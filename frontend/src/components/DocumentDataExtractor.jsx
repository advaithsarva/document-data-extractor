import React, { useState } from 'react';
import './DocumentDataExtractor.css';

// Set REACT_APP_API_URL to point the UI at a deployed backend.
const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:5000';

// The backend decides which entity kinds exist; anything it returns and this
// map knows about gets rendered, so adding a kind server-side needs one line here.
const ENTITY_LABELS = {
  names: ['Names', '👤'],
  dates: ['Dates', '📅'],
  addresses: ['Places', '📍'],
  emails: ['Emails', '✉️'],
  phones: ['Phone numbers', '📞'],
};

function DocumentDataExtractor() {
  const [file, setFile] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showRawData, setShowRawData] = useState(false); // New state for toggling raw data visibility

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      const maxSize = 16 * 1024 * 1024; // 16MB
      if (selectedFile.size > maxSize) {
        alert('File size exceeds 16MB limit. Please choose a smaller file.');
        e.target.value = '';
        return;
      }
      setFile(selectedFile);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      alert('Please select a file.');
      return;
    }

    setIsLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_URL}/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();
      if (response.ok) {
        setResult(data);
      } else {
        setError(data.error || 'Unknown error occurred');
      }
    } catch (err) {
      setError(`Network Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleRawData = () => {
    setShowRawData(!showRawData);
  };

  const displayResults = (data) => {
    if (!data) return null;

    return (
      <div className="result-section">
        <h3>📁 {data.filename} — {data.data.page_count} page{data.data.page_count === 1 ? '' : 's'}</h3>

        <div className="result-section">
          <h3>🔍 Extracted Entities</h3>
          {Object.entries(ENTITY_LABELS).map(([kind, [label, icon]]) => {
            const values = (data.data.entities || {})[kind] || [];
            if (values.length === 0) return null;
            return (
              <div key={kind}>
                <strong>{label}:</strong>
                <div className="entity-list">
                  {values.map((value, index) => (
                    <span key={index} className="entity-item">{icon} {value}</span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {data.data.tables && data.data.tables.length > 0 && (
          <div className="result-section">
            <h3>📊 Tables Found</h3>
            {data.data.tables.map((table, tableIndex) => (
              <div key={tableIndex}>
                <h4>Table {tableIndex + 1}</h4>
                <table style={{ borderCollapse: 'collapse', width: '100%', margin: '10px 0' }}>
                  <thead>
                    {table.headers && (
                      <tr>
                        {table.headers.map((header, headerIndex) => (
                          <th key={headerIndex} style={{ border: '1px solid #ddd', padding: '8px', backgroundColor: '#f2f2f2' }}>
                            {header}
                          </th>
                        ))}
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {table.rows && table.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} style={{ border: '1px solid #ddd', padding: '8px' }}>
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}

        {data.data && (
          <div className="result-section">
            <h3>
              📋 Raw Data
              <button onClick={toggleRawData} style={{ marginLeft: '10px', fontSize: '12px' }}>
                Toggle
              </button>
            </h3>
            <pre style={{ display: showRawData ? 'block' : 'none', background: '#f8f9fa', padding: '10px', borderRadius: '5px', overflowX: 'auto' }}>
              {JSON.stringify(data.data, null, 2)}
            </pre>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="container">
      <h1>📄 Document Data Extractor</h1>

      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="file-input-wrapper">
          <input
            type="file"
            name="file"
            className="file-input"
            accept=".pdf,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.txt"
            onChange={handleFileChange}
            required
          />
          <div className="supported-formats">
            Supported formats: PDF, PNG, JPG, JPEG, GIF, BMP, TIFF, TXT (Max: 16MB)
          </div>
        </div>

        <button type="submit" className="upload-btn" disabled={isLoading}>
          {isLoading ? 'Processing...' : '📤 Upload and Extract Data'}
        </button>
      </form>

      {isLoading && (
        <div className="loading" id="loading">
          <div className="spinner"></div>
          <div>Processing file... Please wait.</div>
        </div>
      )}

      {error && (
        <div id="output" className="error">
          {error}
        </div>
      )}

      {result && (
        <div id="output" className="success">
          {displayResults(result)}
        </div>
      )}
    </div>
  );
}

export default DocumentDataExtractor;
