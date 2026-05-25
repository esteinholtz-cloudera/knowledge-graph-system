"""Entity extraction from text using LLM."""
import json
import re
from typing import List, Dict, Optional
from .llm_client import LLMClient
from .prompts import ENTITY_EXTRACTION_SYSTEM_PROMPT, ENTITY_EXTRACTION_USER_PROMPT


class EntityExtractor:
    """Extract entities from text using LLM."""
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize entity extractor.
        
        Args:
            llm_client: LLM client instance. If None, creates a new one.
        """
        self.llm_client = llm_client or LLMClient.from_config()
    
    def extract(self, text: str) -> List[Dict]:
        """
        Extract entities from text.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            List of entity dictionaries with 'entity', 'type', and optionally 'context'
        """
        # Prepare prompt
        user_prompt = ENTITY_EXTRACTION_USER_PROMPT.format(text=text)
        full_prompt = f"{ENTITY_EXTRACTION_SYSTEM_PROMPT}\n\n{user_prompt}"
        
        # Generate response
        response = self.llm_client.generate(
            prompt=full_prompt,
            stop_words=['\n\n', '```'],
            max_new_tokens=512,
            temperature=0.3  # Lower temperature for more consistent extraction
        )
        
        # Parse JSON from response
        entities = self._parse_json_response(response)
        
        return entities
    
    def _parse_json_response(self, response: str) -> List[Dict]:
        """Parse JSON from LLM response."""
        # Try to extract JSON array from response
        # Look for JSON array pattern
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # Try to find JSON object with entities array
            obj_match = re.search(r'\{.*\}', response, re.DOTALL)
            if obj_match:
                json_str = obj_match.group(0)
            else:
                json_str = response.strip()
        
        try:
            data = json.loads(json_str)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'entities' in data:
                return data['entities']
            else:
                return []
        except json.JSONDecodeError:
            # Try to fix common JSON issues
            json_str = json_str.replace("'", '"')  # Replace single quotes
            json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas
            json_str = re.sub(r',\s*]', ']', json_str)
            
            try:
                data = json.loads(json_str)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'entities' in data:
                    return data['entities']
                else:
                    return []
            except json.JSONDecodeError:
                return []

