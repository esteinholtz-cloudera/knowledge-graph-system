"""Relationship extraction from text using LLM."""
import json
import re
from typing import List, Dict, Optional, Set
from .llm_client import LLMClient
from .prompts import (
    RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
    RELATIONSHIP_EXTRACTION_USER_PROMPT,
    COMBINED_EXTRACTION_SYSTEM_PROMPT,
    COMBINED_EXTRACTION_USER_PROMPT
)


class RelationshipExtractor:
    """Extract relationships between entities using LLM."""
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize relationship extractor.
        
        Args:
            llm_client: LLM client instance. If None, creates a new one.
        """
        self.llm_client = llm_client or LLMClient.from_config()
    
    def extract(self, text: str, entities: Optional[List[str]] = None) -> List[Dict]:
        """
        Extract relationships from text.
        
        Args:
            text: Text to extract relationships from
            entities: Optional list of entity names to focus on
            
        Returns:
            List of triple dictionaries with 'subject', 'predicate', 'object'
        """
        # Prepare prompt
        if entities:
            entity_list = ', '.join(entities[:20])  # Limit to avoid prompt bloat
            user_prompt = RELATIONSHIP_EXTRACTION_USER_PROMPT.format(
                text=text,
                entities=entity_list
            )
            full_prompt = f"{RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT}\n\n{user_prompt}"
        else:
            user_prompt = COMBINED_EXTRACTION_USER_PROMPT.format(text=text)
            full_prompt = f"{COMBINED_EXTRACTION_SYSTEM_PROMPT}\n\n{user_prompt}"
        
        # Generate response
        response = self.llm_client.generate(
            prompt=full_prompt,
            stop_words=['\n\n', '```'],
            max_new_tokens=1024,
            temperature=0.3  # Lower temperature for more consistent extraction
        )
        
        # Parse JSON from response
        triples = self._parse_json_response(response, entities is None)
        
        return triples
    
    def _parse_json_response(self, response: str, is_combined: bool = False) -> List[Dict]:
        """Parse JSON from LLM response."""
        # Try to extract JSON from response
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = response.strip()
        
        try:
            data = json.loads(json_str)
            
            if is_combined:
                # Combined extraction returns object with entities and triples
                if isinstance(data, dict):
                    if 'triples' in data:
                        return data['triples']
                    elif 'relationships' in data:
                        return data['relationships']
                return []
            else:
                # Relationship-only extraction returns array of triples
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'triples' in data:
                    return data['triples']
                elif isinstance(data, dict) and 'relationships' in data:
                    return data['relationships']
                else:
                    return []
        except json.JSONDecodeError:
            # Try to fix common JSON issues
            json_str = json_str.replace("'", '"')
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            
            try:
                data = json.loads(json_str)
                if is_combined:
                    if isinstance(data, dict) and 'triples' in data:
                        return data['triples']
                    return []
                else:
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and 'triples' in data:
                        return data['triples']
                    return []
            except json.JSONDecodeError:
                return []

