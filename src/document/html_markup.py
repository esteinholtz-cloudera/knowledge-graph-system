"""HTML markup generator for annotating documents with extracted entities."""
import re
import html
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from rdflib import Graph
from rdflib.namespace import RDF
from urllib.parse import unquote
from src.storage.rdf_utils import KG, DOC, ONT


class HTMLMarkupGenerator:
    """Generate HTML markup with entities highlighted and labeled."""
    
    # Color scheme for different entity types
    ENTITY_COLORS = {
        'Person': '#4A90E2',  # Blue
        'Organization': '#50C878',  # Green
        'Location': '#FF6B6B',  # Red
        'Technology': '#9B59B6',  # Purple
        'Concept': '#F39C12',  # Orange
        'Product': '#1ABC9C',  # Teal
        'Event': '#E74C3C',  # Dark Red
        'Date': '#3498DB',  # Light Blue
        'Other': '#95A5A6',  # Gray
    }
    
    def __init__(self):
        """Initialize HTML markup generator."""
        pass
    
    def generate_markup_from_ttl(
        self,
        text: str,
        ttl_file_path: str,
        document_filename: str = "document"
    ) -> str:
        """
        Generate HTML markup with entities highlighted, reading entities from TTL file.
        
        Args:
            text: Original document text
            ttl_file_path: Path to the Turtle file containing the knowledge graph
            document_filename: Original document filename (for title)
            
        Returns:
            Complete HTML document as string
        """
        # Parse TTL file to extract entities
        entities = self._extract_entities_from_ttl(ttl_file_path)
        
        # Get unique entities, prioritizing longer names
        unique_entities = self._deduplicate_entities(entities)
        
        # Find all entity matches in text
        matches = self._find_entity_matches(text, unique_entities)
        
        # Sort matches by position, handling overlaps
        sorted_matches = self._resolve_overlaps(matches)
        
        # Build marked-up text
        marked_text = self._apply_markup(text, sorted_matches, unique_entities)
        
        # Generate complete HTML document
        html_doc = self._generate_html_document(marked_text, unique_entities, document_filename, ttl_file_path)
        
        return html_doc
    
    def generate_markup(
        self,
        text: str,
        entities: List[Dict],
        document_filename: str = "document"
    ) -> str:
        """
        Generate HTML markup with entities highlighted (legacy method for backward compatibility).
        
        Args:
            text: Original document text
            entities: List of entity dictionaries with 'entity' and 'type' keys
            document_filename: Original document filename (for title)
            
        Returns:
            Complete HTML document as string
        """
        # Get unique entities, prioritizing longer names
        unique_entities = self._deduplicate_entities(entities)
        
        # Find all entity matches in text
        matches = self._find_entity_matches(text, unique_entities)
        
        # Sort matches by position, handling overlaps
        sorted_matches = self._resolve_overlaps(matches)
        
        # Build marked-up text
        marked_text = self._apply_markup(text, sorted_matches, unique_entities)
        
        # Generate complete HTML document
        html_doc = self._generate_html_document(marked_text, unique_entities, document_filename)
        
        return html_doc
    
    def _extract_entities_from_ttl(self, ttl_file_path: str) -> List[Dict]:
        """
        Extract entities from a Turtle file.
        
        Args:
            ttl_file_path: Path to the Turtle file
            
        Returns:
            List of entity dictionaries with 'entity', 'uri', and optionally 'type'
        """
        entities = []
        entity_uris = set()
        
        # Load the RDF graph
        graph = Graph()
        graph.parse(ttl_file_path, format='turtle')
        
        # Collect only subjects that have a doc:sourceDocument triple —
        # these are definitively entities, not predicates or ontology classes.
        entity_uri_set = set()
        for subject, predicate, obj in graph.triples((None, DOC.sourceDocument, None)):
            if str(subject).startswith(str(KG)):
                entity_uri_set.add(subject)
        
        # Second pass: extract entities with their types
        for entity_uri in entity_uri_set:
            entity_uri_str = str(entity_uri)
            if entity_uri_str not in entity_uris:
                entity_uris.add(entity_uri_str)
                entity_name = self._uri_to_entity_name(entity_uri_str)
                
                # Extract rdf:type if present (from ontology namespace)
                entity_type = 'Other'  # Default
                for s, p, o in graph.triples((entity_uri, RDF.type, None)):
                    if str(o).startswith(str(ONT)):  # Check if it's from our ontology
                        type_name = str(o).replace(str(ONT), '').replace('_', ' ')
                        # Decode URL encoding
                        type_name = unquote(type_name)
                        entity_type = type_name
                        break
                
                entities.append({
                    'entity': entity_name,
                    'uri': entity_uri_str,
                    'type': entity_type
                })
        
        return entities
    
    def _uri_to_entity_name(self, uri: str) -> str:
        """
        Convert entity URI back to entity name.
        
        Args:
            uri: Entity URI (e.g., "http://example.org/kg/Cloudera_Machine_Learning")
            
        Returns:
            Entity name (e.g., "Cloudera Machine Learning")
        """
        # Extract the local name after the namespace
        if str(KG) in uri:
            local_name = uri.replace(str(KG), '')
        else:
            # Fallback: try to extract from any namespace
            parts = uri.split('/')
            local_name = parts[-1] if parts else uri
        
        # Decode URL encoding and replace underscores with spaces
        decoded = unquote(local_name)
        entity_name = decoded.replace('_', ' ')
        
        return entity_name
    
    def _deduplicate_entities(self, entities: List[Dict]) -> Dict[str, Dict]:
        """
        Deduplicate entities, keeping the longest name for each entity.
        
        Args:
            entities: List of entity dictionaries
            
        Returns:
            Dictionary mapping entity names to entity data
        """
        unique = {}
        for entity in entities:
            entity_name = entity.get('entity', '').strip()
            if not entity_name:
                continue
            
            # If entity already exists, keep the longer name
            if entity_name not in unique or len(entity_name) > len(unique[entity_name]['entity']):
                unique[entity_name] = entity
        
        return unique
    
    def _find_entity_matches(self, text: str, entities: Dict[str, Dict]) -> List[Dict]:
        """
        Find all occurrences of entities in text (case-insensitive).
        Uses word boundaries to prevent matching substrings within words.
        
        Args:
            text: Text to search
            entities: Dictionary of entity names to entity data
            
        Returns:
            List of match dictionaries with position, length, and entity info
        """
        matches = []
        
        for entity_name, entity_data in entities.items():
            if not entity_name or not entity_name.strip():
                continue
            
            entity_name = entity_name.strip()
            
            # Escape special regex characters
            escaped_name = re.escape(entity_name)
            
            # Use word boundaries to ensure we match whole words/phrases only
            # \b matches at word boundaries (between word and non-word characters)
            pattern_str = r'\b' + escaped_name + r'\b'
            
            # Case-insensitive search
            pattern = re.compile(pattern_str, re.IGNORECASE)
            
            for match in pattern.finditer(text):
                start_pos = match.start()
                end_pos = match.end()
                matched_text = match.group()
                
                # Additional validation: ensure we're not matching inside a word
                # Check characters immediately before and after the match
                char_before = text[start_pos - 1] if start_pos > 0 else None
                char_after = text[end_pos] if end_pos < len(text) else None
                
                # Word characters are alphanumeric and underscore
                is_word_char = lambda c: c is not None and (c.isalnum() or c == '_')
                
                # If both before and after are word characters, this is inside a word - skip
                if is_word_char(char_before) and is_word_char(char_after):
                    continue
                
                # Verify the matched text matches the entity name (case-insensitive)
                if matched_text.lower() != entity_name.lower():
                    continue
                
                matches.append({
                    'start': start_pos,
                    'end': end_pos,
                    'entity_name': entity_name,
                    'entity_data': entity_data,
                    'matched_text': matched_text
                })
        
        return matches
    
    def _resolve_overlaps(self, matches: List[Dict]) -> List[Dict]:
        """
        Resolve overlapping matches by prioritizing longer matches.
        
        Args:
            matches: List of match dictionaries
            
        Returns:
            Sorted list of non-overlapping matches
        """
        if not matches:
            return []
        
        # Sort by start position, then by length (descending)
        sorted_matches = sorted(matches, key=lambda m: (m['start'], -(m['end'] - m['start'])))
        
        # Remove overlaps, keeping longer matches
        resolved = []
        for match in sorted_matches:
            # Check if this match overlaps with any existing match
            overlaps = False
            for existing in resolved:
                if not (match['end'] <= existing['start'] or match['start'] >= existing['end']):
                    # Overlap detected - keep the longer one
                    if (match['end'] - match['start']) > (existing['end'] - existing['start']):
                        # Current match is longer, replace existing
                        resolved.remove(existing)
                        resolved.append(match)
                    overlaps = True
                    break
            
            if not overlaps:
                resolved.append(match)
        
        # Sort by position for final application
        return sorted(resolved, key=lambda m: m['start'])
    
    def _apply_markup(
        self,
        text: str,
        matches: List[Dict],
        entities: Dict[str, Dict]
    ) -> str:
        """
        Apply HTML markup to text by wrapping entities in spans.
        
        Args:
            text: Original text
            matches: Sorted list of entity matches
            entities: Dictionary of entity data
            
        Returns:
            Text with HTML markup applied
        """
        if not matches:
            # No matches, just escape HTML and preserve formatting
            return self._preserve_formatting(html.escape(text))
        
        # Build marked-up text by processing from end to start
        # (to preserve indices)
        result = []
        last_pos = 0
        
        for match in matches:
            # Add text before match
            before_text = text[last_pos:match['start']]
            result.append(self._preserve_formatting(html.escape(before_text)))
            
            # Add marked-up entity
            entity_name = match['entity_name']
            entity_data = match['entity_data']
            entity_type = entity_data.get('type', 'Other')
            entity_uri = entity_data.get('uri', '')
            matched_text = match['matched_text']
            
            # Get color for entity type
            color = self.ENTITY_COLORS.get(entity_type, self.ENTITY_COLORS['Other'])
            
            # Create span with badge
            span_class = f"entity-{entity_type.lower().replace(' ', '-')}"
            
            # If entity has URI, make it a link
            entity_text = html.escape(matched_text)
            if entity_uri:
                entity_text = f'<a href="{html.escape(entity_uri)}" target="_blank" title="Entity URI: {html.escape(entity_uri)}" style="text-decoration: none; color: inherit;">{entity_text}</a>'
            
            marked_entity = (
                f'<span class="entity {span_class}" style="background-color: {color}20; '
                f'border-left: 3px solid {color}; padding: 2px 4px; position: relative;">'
                f'{entity_text}'
                f'<span class="entity-badge" style="background-color: {color}; color: white; '
                f'font-size: 0.7em; padding: 1px 4px; margin-left: 4px; border-radius: 3px; '
                f'font-weight: bold;">{html.escape(entity_type)}</span>'
                f'</span>'
            )
            result.append(marked_entity)
            
            last_pos = match['end']
        
        # Add remaining text
        remaining_text = text[last_pos:]
        result.append(self._preserve_formatting(html.escape(remaining_text)))
        
        return ''.join(result)
    
    def _preserve_formatting(self, text: str) -> str:
        """
        Preserve basic text formatting (line breaks, paragraphs).
        
        Args:
            text: Text to format
            
        Returns:
            Text with formatting preserved
        """
        if not text:
            return text
        # Use double <br> for paragraph breaks — avoids broken <p> nesting
        # when this result is embedded inside an outer <p> in the template.
        text = re.sub(r'\n\n+', '<br><br>', text)
        text = re.sub(r'\n', '<br>', text)
        return text
    
    def _generate_html_document(
        self,
        marked_text: str,
        entities: Dict[str, Dict],
        document_filename: str,
        ttl_file_path: Optional[str] = None
    ) -> str:
        """
        Generate complete HTML document with styling.
        
        Args:
            marked_text: Text with entity markup applied
            entities: Dictionary of entities
            document_filename: Original document filename
            ttl_file_path: Optional path to the Turtle file
            
        Returns:
            Complete HTML document
        """
        # Get unique entity types for legend
        entity_types = set()
        for entity_data in entities.values():
            entity_type = entity_data.get('type', 'Other')
            entity_types.add(entity_type)
        
        # Build legend HTML
        legend_html = self._generate_legend(entity_types)
        
        # Build entity list HTML
        entity_list_html = self._generate_entity_list(entities)
        
        # Build TTL file link if available
        ttl_link_html = ""
        if ttl_file_path:
            ttl_file_path_escaped = html.escape(ttl_file_path)
            ttl_link_html = f'<div style="margin-top: 10px;"><a href="file://{ttl_file_path_escaped}" target="_blank" style="color: #4A90E2; text-decoration: none;">📄 View Knowledge Graph (TTL)</a></div>'
        
        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Entity Markup - {html.escape(document_filename)}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        h1 {{
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 2em;
        }}
        
        .document-info {{
            color: #7f8c8d;
            margin-bottom: 30px;
            font-size: 0.9em;
        }}
        
        .legend {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 30px;
        }}
        
        .legend h2 {{
            font-size: 1.2em;
            margin-bottom: 15px;
            color: #2c3e50;
        }}
        
        .legend-items {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 3px;
            border: 1px solid #ddd;
        }}
        
        .entity-list {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 30px;
            max-height: 300px;
            overflow-y: auto;
        }}
        
        .entity-list h2 {{
            font-size: 1.2em;
            margin-bottom: 15px;
            color: #2c3e50;
        }}
        
        .entity-list ul {{
            list-style: none;
            columns: 2;
            column-gap: 20px;
        }}
        
        .entity-list li {{
            margin-bottom: 5px;
            break-inside: avoid;
        }}
        
        .entity-list .entity-name {{
            font-weight: 500;
        }}
        
        .entity-list .entity-type {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        
        .document-content {{
            background-color: white;
            padding: 30px;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            line-height: 1.8;
        }}
        
        .document-content p {{
            margin-bottom: 1em;
        }}
        
        .entity {{
            display: inline-block;
            margin: 0 2px;
            border-radius: 3px;
            cursor: help;
        }}
        
        .entity-badge {{
            display: inline-block;
            vertical-align: middle;
            font-size: 0.7em;
            padding: 1px 4px;
            margin-left: 4px;
            border-radius: 3px;
            font-weight: bold;
            white-space: nowrap;
        }}
        
        @media print {{
            body {{
                background-color: white;
                padding: 0;
            }}
            
            .container {{
                box-shadow: none;
                padding: 20px;
            }}
            
            .legend, .entity-list {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Entity Markup</h1>
        <div class="document-info">
            Document: {html.escape(document_filename)}
            {ttl_link_html}
        </div>
        
        {legend_html}
        
        {entity_list_html}
        
        <div class="document-content">
            <div class="document-text">{marked_text}</div>
        </div>
    </div>
</body>
</html>"""
        
        return html_template
    
    def _generate_legend(self, entity_types: set) -> str:
        """
        Generate HTML for entity type legend.
        
        Args:
            entity_types: Set of entity type names
            
        Returns:
            HTML string for legend
        """
        if not entity_types:
            return ""
        
        items = []
        for entity_type in sorted(entity_types):
            color = self.ENTITY_COLORS.get(entity_type, self.ENTITY_COLORS['Other'])
            items.append(
                f'<div class="legend-item">'
                f'<div class="legend-color" style="background-color: {color};"></div>'
                f'<span>{html.escape(entity_type)}</span>'
                f'</div>'
            )
        
        return f"""<div class="legend">
            <h2>Entity Types</h2>
            <div class="legend-items">
                {''.join(items)}
            </div>
        </div>"""
    
    def _generate_entity_list(self, entities: Dict[str, Dict]) -> str:
        """
        Generate HTML for entity list.
        
        Args:
            entities: Dictionary of entities
            
        Returns:
            HTML string for entity list
        """
        if not entities:
            return ""
        
        items = []
        for entity_name, entity_data in sorted(entities.items()):
            entity_type = entity_data.get('type', 'Other')
            items.append(
                f'<li>'
                f'<span class="entity-name">{html.escape(entity_name)}</span> '
                f'<span class="entity-type">({html.escape(entity_type)})</span>'
                f'</li>'
            )
        
        return f"""<div class="entity-list">
            <h2>Extracted Entities ({len(entities)})</h2>
            <ul>
                {''.join(items)}
            </ul>
        </div>"""
    
    def save_markup(
        self,
        html_content: str,
        output_path: str
    ) -> str:
        """
        Save HTML markup to file.
        
        Args:
            html_content: Complete HTML document
            output_path: Path where to save the HTML file
            
        Returns:
            Path to saved file
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(output_file)

