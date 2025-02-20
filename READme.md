# Enhanced Name Extractor

A powerful web-based tool that extracts names from various document formats and text inputs. This tool provides an intuitive interface for identifying and extracting names from documents, with integrated search capabilities for quick verification.

## Features

- **Multiple Input Sources**
  - File upload support for DOCX, PDF, and CSV files
  - Direct text input
  - Drag-and-drop file interface

- **Smart Name Detection**
  - Identifies proper names using capitalization patterns
  - Filters out common words and false positives
  - Extracts names from email addresses
  - Handles multiple name formats

- **Search Integration**
  - Direct links to Google search for each extracted name
  - LinkedIn search integration for professional verification
  - Organized table view of results

- **User-Friendly Interface**
  - Clean, modern design
  - Real-time status updates
  - Responsive layout
  - File management capabilities

## Getting Started

### Prerequisites

The application requires a modern web browser with JavaScript enabled. No server-side installation is needed.

### Installation

1. Clone this repository:

git clone https://github.com/yourusername/enhanced-name-extractor.git

2. Open `name-extractor-ui.html` in a web browser.

### Usage

1. **Input your data:**
   - Drag and drop supported files into the designated area
   - Click "Browse Files" to select files manually
   - Paste text directly into the text area

2. **Process the data:**
   - Click "Extract Names" to begin processing
   - Wait for the extraction to complete

3. **Review results:**
   - View the extracted names in the results table
   - Use the provided search links to verify names
   - Sort results alphabetically

## Technical Details

### Dependencies

- [Mammoth.js](https://github.com/mwilliamson/mammoth.js) - For DOCX processing
- [PDF.js](https://mozilla.github.io/pdf.js/) - For PDF processing
- [Papa Parse](https://www.papaparse.com/) - For CSV processing

### Name Detection Algorithm

The tool uses several strategies to identify names:
- Capitalization patterns
- Common word filtering
- Email address parsing
- Multi-word name detection

## Browser Compatibility

- Chrome (recommended)
- Firefox
- Safari
- Edge

## Limitations

- Only processes text-based PDFs
- Maximum file size depends on browser limitations
- Names must follow standard capitalization rules
- May not detect non-Western name formats

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- PDF.js by Mozilla
- Mammoth.js contributors
- Papa Parse team

## Support

For issues and feature requests, please open an issue in the GitHub repository.