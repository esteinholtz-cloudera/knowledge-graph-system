"""Client for interacting with the existing RAG LLM."""
import sys
import os
from pathlib import Path
from typing import Optional


class LLMClient:
    """Client wrapper for the existing RAG chatbot LLM."""
    
    def __init__(self, rag_project_path: Optional[str] = None):
        """
        Initialize LLM client.
        
        Args:
            rag_project_path: Path to the RAG chatbot project directory.
                             If None, will try to find it automatically.
        """
        self.rag_project_path = rag_project_path or self._find_rag_project()
        self._llm_module = None
        self._loaded = False
    
    def _find_rag_project(self) -> str:
        """Try to find the RAG project path."""
        # Look for the RAG project in common locations
        current_dir = Path(__file__).parent.parent.parent.parent
        
        # Check current directory
        rag_path = current_dir / "_CML_AMP_LLM_Chatbot_Augmented_with_Enterprise_Data"
        if rag_path.exists() and (rag_path / "utils" / "model_llm_utils.py").exists():
            return str(rag_path)
        
        # Check parent directory
        parent_rag_path = current_dir.parent / "_CML_AMP_LLM_Chatbot_Augmented_with_Enterprise_Data"
        if parent_rag_path.exists() and (parent_rag_path / "utils" / "model_llm_utils.py").exists():
            return str(parent_rag_path)
        
        # Check if we're already in the RAG project
        if (current_dir / "utils" / "model_llm_utils.py").exists():
            return str(current_dir)
        
        raise FileNotFoundError(
            "Could not find RAG chatbot project. Please specify rag_project_path "
            "when initializing LLMClient, or ensure the project is in the expected location."
        )
    
    def _load_llm(self):
        """Lazy load the LLM module."""
        if self._loaded:
            return
        
        # Add RAG project utils to path
        utils_path = os.path.join(self.rag_project_path, 'utils')
        if utils_path not in sys.path:
            sys.path.insert(0, utils_path)
        
        try:
            # Import the LLM utilities
            import model_llm_utils
            self._llm_module = model_llm_utils
            self._loaded = True
        except ImportError as e:
            raise ImportError(
                f"Failed to import LLM utilities from {utils_path}. "
                f"Make sure the RAG project is properly set up. Error: {e}"
            )
    
    def generate(
        self,
        prompt: str,
        stop_words: Optional[list] = None,
        temperature: float = 0.7,
        max_new_tokens: int = 512,
        top_p: float = 0.85,
        top_k: int = 70,
        repetition_penalty: float = 1.07,
        do_sample: bool = False
    ) -> str:
        """
        Generate text using the LLM.
        
        Args:
            prompt: Input prompt
            stop_words: List of stop words
            temperature: Sampling temperature
            max_new_tokens: Maximum tokens to generate
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            repetition_penalty: Repetition penalty
            do_sample: Whether to use sampling
            
        Returns:
            Generated text
        """
        self._load_llm()
        
        if stop_words is None:
            stop_words = ['\n\n', '```', 'JSON']
        
        return self._llm_module.get_llm_generation(
            prompt=prompt,
            stop_words=stop_words,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            do_sample=do_sample
        )

