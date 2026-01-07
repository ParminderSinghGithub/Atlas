import React from 'react';

interface StructuredDescriptionProps {
  description: string;
}

interface Section {
  title: string;
  content: string[];
}

export const StructuredDescription: React.FC<StructuredDescriptionProps> = ({ description }) => {
  // Parse the description into sections
  const parseDescription = (text: string): Section[] => {
    if (!text) return [];

    // Common section headers to look for (in order of priority)
    const sectionHeaders = [
      'Package List:',
      'Package Includes:',
      'What\'s in the Box:',
      'System Requirements:',
      'Technical Specifications:',
      'Specifications:',
      'Product Features:',
      'Features:',
      'Details:',
      'Description:',
      'Requirements:',
      'Installation:',
      'Usage:',
      'Notes:',
    ];

    // Check if the text contains any section headers
    const hasSections = sectionHeaders.some(header => 
      text.toLowerCase().includes(header.toLowerCase())
    );

    // Also check for numbered list patterns (e.g., "5 Easy Ways", "3 Simple Steps")
    const hasNumberedTitle = /\d+\s+(Easy|Simple|Quick|Best|Top)\s+\w+/i.test(text);

    if (!hasSections && !hasNumberedTitle) {
      // Plain description - return as single section
      return [{ title: '', content: text.split('\n').filter(line => line.trim()) }];
    }

    const sections: Section[] = [];
    
    // First, try to detect numbered section titles (e.g., "5 Easy Ways to Create...")
    const numberedTitleMatch = text.match(/(\d+\s+(?:Easy|Simple|Quick|Best|Top)\s+\w+[^:]*?)(?=\s+1\.)/i);
    
    // Split text by section headers using regex
    let remainingText = text;
    let firstSection = '';
    
    // If we found a numbered title pattern, extract it as the first section
    if (numberedTitleMatch && numberedTitleMatch.index !== undefined) {
      firstSection = text.substring(0, numberedTitleMatch.index).trim();
      const titleEnd = numberedTitleMatch.index + numberedTitleMatch[1].length;
      
      if (firstSection) {
        sections.push({
          title: '',
          content: firstSection.split('\n').map(l => l.trim()).filter(l => l)
        });
      }
      
      // Add the numbered title as a section header
      sections.push({
        title: numberedTitleMatch[1].trim(),
        content: []
      });
      
      remainingText = text.substring(titleEnd).trim();
    }
    
    // Find the position of the first section header (with colon)
    let firstHeaderPos = -1;
    
    for (const header of sectionHeaders) {
      const pos = remainingText.toLowerCase().indexOf(header.toLowerCase());
      if (pos !== -1 && (firstHeaderPos === -1 || pos < firstHeaderPos)) {
        firstHeaderPos = pos;
      }
    }
    
    // Extract content before first header
    if (firstHeaderPos > 0) {
      firstSection = remainingText.substring(0, firstHeaderPos).trim();
      if (firstSection) {
        sections.push({
          title: '',
          content: firstSection.split('\n').map(l => l.trim()).filter(l => l)
        });
      }
      remainingText = remainingText.substring(firstHeaderPos);
    }
    
    // Now split remaining text by all headers
    while (remainingText) {
      let foundHeader = '';
      let foundPos = -1;
      
      // Find the next section header
      for (const header of sectionHeaders) {
        const regex = new RegExp(header.replace(':', '\\:'), 'i');
        const match = remainingText.match(regex);
        if (match && match.index !== undefined) {
          if (foundPos === -1 || match.index < foundPos) {
            foundPos = match.index;
            foundHeader = header;
          }
        }
      }
      
      if (foundPos === -1 || foundPos > 0) {
        // No header found or header not at start - shouldn't happen now
        break;
      }
      
      // Extract content after this header until next header
      const afterHeader = remainingText.substring(foundHeader.length).trim();
      let nextHeaderPos = afterHeader.length;
      
      for (const header of sectionHeaders) {
        const regex = new RegExp(header.replace(':', '\\:'), 'i');
        const match = afterHeader.match(regex);
        if (match && match.index !== undefined && match.index < nextHeaderPos) {
          nextHeaderPos = match.index;
        }
      }
      
      const sectionContent = afterHeader.substring(0, nextHeaderPos).trim();
      
      if (sectionContent) {
        // Split content by newlines and also detect subsections that might be on same line
        let contentLines = sectionContent.split('\n').map(l => l.trim()).filter(l => l);
        
        // Further split lines that have multiple subsections (pattern: "Label1: content Label2: content")
        const expandedLines: string[] = [];
        for (const line of contentLines) {
          // Find all subsection patterns in the line
          const subsectionPattern = /([A-Za-z0-9\s\-\/]{3,40}):\s*([^:]{1,100}?)(?=\s+[A-Z][A-Za-z0-9\s\-\/]{2,40}:|$)/g;
          const matches = [...line.matchAll(subsectionPattern)];
          
          if (matches.length > 1) {
            // Multiple subsections on same line - split them
            matches.forEach(match => {
              const fullMatch = `${match[1]}: ${match[2]}`.trim();
              if (fullMatch.length > 5) {
                expandedLines.push(fullMatch);
              }
            });
          } else {
            // Single line or no subsections
            expandedLines.push(line);
          }
        }
        
        sections.push({
          title: foundHeader.replace(':', ''),
          content: expandedLines
        });
      }
      
      // Move to next section
      if (nextHeaderPos < afterHeader.length) {
        remainingText = afterHeader.substring(nextHeaderPos);
      } else {
        break;
      }
    }

    return sections;
  };

  const sections = parseDescription(description);

  // Render a single line (detect if it's a bullet point, numbered item, or subsection)
  const renderLine = (line: string, index: number) => {
    // Check if line starts with bullet point indicators
    const bulletPatterns = /^[•\-\*\+]\s+/;
    const numberedPattern = /^\d+\.\s+/;
    const isBullet = bulletPatterns.test(line);
    const isNumbered = numberedPattern.test(line);

    if (isBullet) {
      const content = line.replace(bulletPatterns, '');
      return (
        <li key={index} className="ml-4">
          {content}
        </li>
      );
    }

    if (isNumbered) {
      const content = line.replace(numberedPattern, '');
      return (
        <li key={index} className="ml-4">
          {content}
        </li>
      );
    }

    // Check if line is a subsection header (word(s) followed by colon)
    // Examples: "Supported OS:", "Hard Disk Space:", "Video:", etc.
    const subsectionPattern = /^([A-Za-z0-9\s\-\/]+):\s*(.*)$/;
    const subsectionMatch = line.match(subsectionPattern);
    
    if (subsectionMatch) {
      const [, label, content] = subsectionMatch;
      // Only treat as subsection if label is relatively short (< 50 chars) and not a URL
      if (label.length < 50 && !label.includes('http') && !label.includes('www')) {
        return (
          <div key={index} className="mb-2">
            <span className="font-semibold text-gray-900">{label}:</span>
            {content && <span className="ml-2 text-gray-700">{content}</span>}
          </div>
        );
      }
    }

    return (
      <p key={index} className="mb-2">
        {line}
      </p>
    );
  };

  return (
    <div className="space-y-6">
      {sections.map((section, sectionIndex) => (
        <div key={sectionIndex}>
          {section.title && (
            <h3 className="text-lg font-semibold text-gray-900 mb-3 border-b border-gray-200 pb-2">
              {section.title}
            </h3>
          )}
          <div className="text-gray-700 space-y-1">
            {section.content.map((line, lineIndex) => {
              // Check if multiple lines in a row start with bullets or numbers - render as list
              const isBullet = /^[•\-\*\+]\s+/.test(line);
              const isNumbered = /^\d+\.\s+/.test(line);
              const isListItem = isBullet || isNumbered;
              const prevIsBullet = lineIndex > 0 && /^[•\-\*\+]\s+/.test(section.content[lineIndex - 1]);
              const prevIsNumbered = lineIndex > 0 && /^\d+\.\s+/.test(section.content[lineIndex - 1]);
              const prevIsListItem = prevIsBullet || prevIsNumbered;

              // Start of list
              if (isListItem && !prevIsListItem) {
                const listLines = [];
                let i = lineIndex;
                while (i < section.content.length && (/^[•\-\*\+]\s+/.test(section.content[i]) || /^\d+\.\s+/.test(section.content[i]))) {
                  listLines.push(section.content[i]);
                  i++;
                }
                // Render as list if we have multiple items
                if (listLines.length > 0) {
                  const isOrderedList = /^\d+\.\s+/.test(listLines[0]);
                  const ListTag = isOrderedList ? 'ol' : 'ul';
                  const listClass = isOrderedList ? 'list-decimal list-inside space-y-1 mb-3' : 'list-disc list-inside space-y-1 mb-3';
                  
                  return (
                    <ListTag key={lineIndex} className={listClass}>
                      {listLines.map((listLine, idx) => {
                        const content = listLine.replace(/^(?:[•\-\*\+]|\d+\.)\s+/, '');
                        return (
                          <li key={idx} className="ml-2">
                            {content}
                          </li>
                        );
                      })}
                    </ListTag>
                  );
                }
              }

              // Skip if already rendered as part of a list
              if (isListItem && prevIsListItem) {
                return null;
              }

              // Regular line
              return renderLine(line, lineIndex);
            })}
          </div>
        </div>
      ))}
    </div>
  );
};
