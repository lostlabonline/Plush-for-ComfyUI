from abc import ABC, abstractmethod
import torch
import time
import re
import requests
from urllib.parse import urlparse, urlunparse
import openai
from .mng_json import json_manager, TroubleSgltn

class ImportedSgltn:
    """
    This class is temporary to prevent circular imports
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ImportedSgltn, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized: #pylint: disable=access-member-before-definition
            self._initialized = True
            self._cfig = None
            self._dalle = None
            self._request_mode = None
            self.get_imports()

    def get_imports(self):
        # Guard against re-importing if already done
        if self._cfig is None or self._dalle is None:
            from .style_prompt import cFigSingleton, DalleImage, RequestMode #pylint: disable=import-outside-toplevel
            self._cfig = cFigSingleton
            self._dalle = DalleImage
            self._request_mode = RequestMode


    @property
    def cfig(self):

        if self._cfig is None:
            self.get_imports()
        return self._cfig

    @property
    def dalle(self):

        if self._dalle is None:
            self.get_imports()
        return self._dalle
    
    
    @property
    def request_mode(self):

        if self._request_mode is None:
            self.get_imports()
        return self._request_mode
    

#Begin Strategy Pattern
class Request(ABC):

    def __init__(self):
        self.imps = ImportedSgltn()
        self.utils = request_utils()
        self.cFig = self.imps.cfig()
        self.mode = self.imps.request_mode
        self.dalle = self.imps.dalle()
        self.j_mngr = json_manager()

    @abstractmethod
    def request_completion(self, **kwargs) -> None:
        pass

class oai_object_request(Request): #Concrete class

 
    def request_completion(self, **kwargs):
        
        GPTmodel = kwargs.get('model')
        creative_latitude = kwargs.get('creative_latitude', 0.7)
        tokens = kwargs.get('tokens',500)
        prompt = kwargs.get('prompt', "")
        instruction = kwargs.get('instruction', "")
        file = kwargs.get('file',"")
        image = kwargs.get('image', None)
        example_list = kwargs.get('example_list', [])
        request_type = kwargs.get('request_type',self.mode.OPENAI)

        response = None
        CGPT_response = ""
        file += file.strip()

        if request_type == self.mode.OPENSOURCE:
            if self.cFig.lm_url:
                self.j_mngr.log_events("Setting client to OpenAI Open Source LLM object",
                                    is_trouble=True)
                client = self.cFig.lm_client
            else:
                self.j_mngr.log_events("Open Source api object is not ready for use, no URL provided. Aborting",
                                  TroubleSgltn.Severity.WARNING,
                                    is_trouble=True)
                return CGPT_response
        else:
            if self.cFig.key:
                self.j_mngr.log_events("Setting client to OpenAI ChatGPT object",
                                    is_trouble=True)
                client = self.cFig.openaiClient
            else:
                CGPT_response = "Invalid or missing OpenAI API key.  Keys must be stored in an environment variable (see: ReadMe). ChatGPT request aborted"
                self.j_mngr.log_events("Invalid or missing OpenAI API key.  Keys must be stored in an environment variable (see: ReadMe). ChatGPT request aborted",
                                  TroubleSgltn.Severity.WARNING,
                                    is_trouble=True)
                return CGPT_response



        if not client:
            if request_type ==  self.mode.OPENAI:
                self.j_mngr.log_events("Invalid or missing OpenAI API key.  Keys must be stored in an environment variable (see: ReadMe). ChatGPT request aborted",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
                CGPT_response = "Invalid or missing OpenAI API key.  Keys must be stored in an environment variable (see: ReadMe). ChatGPT request aborted"

            elif request_type == self.mode.OPENSOURCE :
                self.j_mngr.log_events("Open Source LLM client not set.  Make sure local Server is running",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
                CGPT_response = "Unable to process request, make sure local server is running"                
            return CGPT_response

        #there's an image
        if image:
            # Use the user's selected vision model if it's what was chosen,
            #otherwise use the last vision model in the list
            #If the user is using a local LLM they're on their own to make
            #the right model selection for handling an image

            if isinstance(image, torch.Tensor):  #just to be sure
                image = self.dalle.tensor_to_base64(image)
                
            if not isinstance(image,str):
                image = None
                self.j_mngr.log_events("Image file is invalid.  Image will be disregarded in the generated output.",
                                  TroubleSgltn.Severity.WARNING,
                                  True)
            else:
                if request_type == self.mode.OPENAI:
                    models = self.cFig.get_chat_models(True, 'gpt-4')
                    if 'gpt-4-turbo-2024-04-09' in models:
                        GPTmodel = 'gpt-4-turbo'
                    else:
                        GPTmodel = 'gpt-4-vision-preview'

        messages = []

        messages = self.utils.build_data_multi(prompt, instruction, example_list, image)
            
        if not prompt and not image and not instruction:
            # User has provided no prompt, file or image
            response = "Photograph of an stained empty box with 'NOTHING' printed on its side in bold letters, small flying moths, dingy, gloomy, dim light rundown warehouse"
            self.j_mngr.log_events("No instruction and no prompt were provided, the node was only able to provide a 'Box of Nothing'",
                              TroubleSgltn.Severity.WARNING,
                              True)
            return response

        params = {
        "model": GPTmodel,
        "messages": messages,
        "temperature": creative_latitude,
        "max_tokens": tokens
        }

        try:
            response = client.chat.completions.create(**params)

        except openai.APIConnectionError as e: # from httpx.
            self.j_mngr.log_events(f"Server connection error: {e.__cause__}",                                   
                                    TroubleSgltn.Severity.ERROR,
                                    True)
            if request_type == self.mode.OPENSOURCE:
                self.j_mngr.log_events(f"Local server is not responding to the URL: {self.cFig.lm_url}.  Make sure your LLM Manager/Front-end app is running and its local server is live.",
                                TroubleSgltn.Severity.WARNING,
                                True)
        except openai.RateLimitError as e:
            self.j_mngr.log_events(f"Server RATE LIMIT error {e.status_code}: {e.response}",
                                TroubleSgltn.Severity.ERROR,
                                    True)
        except openai.APIStatusError as e:
            self.j_mngr.log_events(f"Server STATUS error {e.status_code}: {e.response}. File may be too large.",
                                TroubleSgltn.Severity.ERROR,
                                    True)
        except Exception as e:
            self.j_mngr.log_events(f"An unexpected server error occurred.: {e}",
                                TroubleSgltn.Severity.ERROR,
                                    True)


        if response and 'error' not in response:
            rpt_model = ""
            try:
                rpt_model = response.model
                rpt_usage = response.usage
            except Exception as e:
                self.j_mngr.log_events(f"Unable to report some completion information, error: {e}",
                                  TroubleSgltn.Severity.INFO,
                                  True)
            if rpt_model:    
                self.j_mngr.log_events(f"Using LLM: {rpt_model}",                                  
                               is_trouble=True)
            if rpt_usage:
                self.j_mngr.log_events(f"Tokens Used: {rpt_usage}",
                                  TroubleSgltn.Severity.INFO,
                                  True)
            CGPT_response = response.choices[0].message.content
            CGPT_response = self.utils.clean_response_text(CGPT_response)
        else:
            CGPT_response = "Server was unable to process the request"
            self.j_mngr.log_events('Server was unable to process this request.',
                                TroubleSgltn.Severity.ERROR,
                                True)
        return CGPT_response

class oai_web_request(Request):


    def request_completion(self, **kwargs):

        """
        Uses the incoming arguments to construct a JSON that contains the request for an LLM response.
        Accesses an LLM via an http POST.
        Sends the request via http. Handles the OpenAI return object and extacts the model and the response from it.

        Args:
            GPTmodel (str):  The ChatGPT model to use in processing the request. Alternately this serves as a flag that the function will processing open source LLM data (GPTmodel = "LLM")
            creative_latitude (float): A number setting the 'temperature' of the LLM
            tokens (int): A number indicating the max number of tokens used to process the request and response
            url (str): The url for the server the information is being sent to
            request_:type (Enum): Specifies whether the function will be using a ChatGPT configured api object or an third party/url configured api object.
            prompt (str): The users' request to action by the LLM
            instruction (str): Text describing the conditions and specific requirements of the return value
            image (b64 JSON/str): An image to be evaluated by the LLM in the context of the instruction

        Return:
            A string consisting of the LLM's response to the instruction and prompt in the context of any image and/or file
        """
        GPTmodel = kwargs.get('model', "")
        creative_latitude = kwargs.get('creative_latitude', 0.7)
        url = kwargs.get('url',None)
        tokens = kwargs.get('tokens', 500)
        image = kwargs.get('image', None)
        prompt = kwargs.get('prompt', None)
        instruction = kwargs.get('instruction', "")
        request_type = kwargs.get('request_type', self.mode.OOBABOOGA)
        example_list = kwargs.get('example_list', [])

        response = None
        CGPT_response = ""    

        #there's an image
        if image:
            #The user is on their own to make
            #the right model selection for handling an image
            if isinstance(image, torch.Tensor):  #just to be sure
                image = self.dalle.tensor_to_base64(image)
                
            if not isinstance(image,str):
                image = None
                self.j_mngr.log_events("Image file is invalid.  Image will be disregarded in the generated output.",
                                  TroubleSgltn.Severity.WARNING,
                                  True)

        key = ""
        if request_type == self.mode.OPENAI:
            key =  self.cFig.key
        else:
            key = self.cFig.lm_key
                
        headers = self.utils.build_web_header(key) 
        
        messages = self.utils.build_data_multi(prompt,instruction,example_list, image)

        params = {
        "model": GPTmodel,
        "messages": messages,
        "temperature": creative_latitude,
        "max_tokens": tokens
        }    

        post_success = False
        response_json = ""
        #payload = {**params}
        try:
            response = requests.post(url, headers=headers, json=params, timeout=(12,120))
            
            if response.status_code in range(200, 300):
                response_json = response.json()
                if response_json and not 'error' in response_json:
                    CGPT_response = self.utils.clean_response_text(response_json['choices'][0]['message']['content'] )
                    post_success = True
                else:
                    error_message = response_json.get('error', 'Unknown error')
                    self.j_mngr.log_events(f"Server was unable to process the response. Error: {error_message}",
                                    TroubleSgltn.Severity.ERROR,
                                    True)
            else:
                CGPT_response = 'Server was unable to process this request'
                self.j_mngr.log_events(f"Server was unable to process the request.  Status: {response.status_code}: {response.text}",
                                    TroubleSgltn.Severity.ERROR,
                                    True)
                
        except Exception as e:
            self.j_mngr.log_events(f"Unable to send data to server.  Error: {e}",
                              TroubleSgltn.Severity.ERROR,
                              True)
        if post_success:   
            try:
                rpt_model = response_json['model']
                rpt_usage = response_json['usage']
                if rpt_model:    
                    self.j_mngr.log_events(f"Using LLM: {rpt_model}",                                  
                                is_trouble=True)
                if rpt_usage:
                    self.j_mngr.log_events(f"Tokens Used: {rpt_usage}",
                                        is_trouble=True)

            except Exception as e:
                self.j_mngr.log_events(f"Unable to report some completion information: model, usage.  Error: {e}",
                                    TroubleSgltn.Severity.INFO,
                                    True)    

        return CGPT_response


class ooba_web_request(Request):


    def request_completion(self, **kwargs):

        """
        Accesses an OpenAI API client and uses the incoming arguments to construct a JSON that contains the request for an LLM response.
        Sends the request via the client. Handles the OpenAI return object and extacts the model and the response from it.

        Args:
            GPTmodel (str):  The ChatGPT model to use in processing the request. Alternately this serves as a flag that the function will processing open source LLM data (GPTmodel = "LLM")
            creative_latitude (float): A number setting the 'temperature' of the LLM
            tokens (int): A number indicating the max number of tokens used to process the request and response
            url (str): The url for the server the information is being sent to
            request_:type (Enum): Specifies whether the function will be using a ChatGPT configured api object or an third party/url configured api object.
            prompt (str): The users' request to action by the LLM
            instruction (str): Text describing the conditions and specific requirements of the return value
            image (b64 JSON/str): An image to be evaluated by the LLM in the context of the instruction

        Return:
            A string consisting of the LLM's response to the instruction and prompt in the context of any image and/or file
        """
        GPTmodel = kwargs.get('model', "")
        creative_latitude = kwargs.get('creative_latitude', 0.7)
        url = kwargs.get('url',None)
        tokens = kwargs.get('tokens', 500)
        image = kwargs.get('image', None)
        prompt = kwargs.get('prompt', None)
        instruction = kwargs.get('instruction', "")
        request_type = kwargs.get('request_type', self.mode.OOBABOOGA)
        example_list = kwargs.get('example_list', [])

        response = None
        CGPT_response = ""    

        url = self.utils.validate_and_correct_url(url) #validate v1/chat/completions path

        #image code is here, but right now none of the tested LLM front ends can handle them 
        #when using an http POST
        if image:
            image = None
            self.j_mngr.log_events('Images not supported in this mode at this time.  Image not transmitted',
                              TroubleSgltn.Severity.WARNING,
                              True)   

        key = ""
        if request_type == self.mode.OPENAI:
            key =  self.cFig.key
        else:
            key = self.cFig.lm_key
                
        headers = self.utils.build_web_header(key) 

        #messages = self.utils.build_data_basic(prompt, example_list, instruction)
        
        messages = self.utils.build_data_ooba(prompt, example_list, instruction)

        if request_type == self.mode.OOBABOOGA:
            self.j_mngr.log_events(f"Processing Oobabooga http: POST request with url: {url}",
                              is_trouble=True)
            params = {
            "model": GPTmodel,
            "messages": messages,
            "temperature": creative_latitude,
            "max_tokens": tokens,
            "user_bio": "",
            "user_name": ""
            }
        else:
            params = {
            "model": GPTmodel,
            "messages": messages,
            "temperature": creative_latitude,
            "max_tokens": tokens
            }    
        post_success = False
        response_json = ""
        #payload = {**params}
        try:
            response = requests.post(url, headers=headers, json=params, timeout=(12,120))
            
            if response.status_code in range(200, 300):
                response_json = response.json()
                if response_json and not 'error' in response_json:
                    CGPT_response = self.utils.clean_response_text(response_json['choices'][0]['message']['content'] )
                    post_success = True
                else:
                    error_message = response_json.get('error', 'Unknown error')
                    self.j_mngr.log_events(f"Server was unable to process the response. Error: {error_message}",
                                    TroubleSgltn.Severity.ERROR,
                                    True)
            else:
                CGPT_response = 'Server was unable to process this request'
                self.j_mngr.log_events(f"Server was unable to process the request.  Status: {response.status_code}: {response.text}",
                                    TroubleSgltn.Severity.ERROR,
                                    True)
                
        except Exception as e:
            self.j_mngr.log_events(f"Unable to send data to server.  Error: {e}",
                              TroubleSgltn.Severity.ERROR,
                              True)
        if post_success:   
            try:
                rpt_model = response_json['model']
                rpt_usage = response_json['usage']
                if rpt_model:    
                    self.j_mngr.log_events(f"Using LLM: {rpt_model}",                                  
                                is_trouble=True)
                if rpt_usage:
                    self.j_mngr.log_events(f"Tokens Used: {rpt_usage}",
                                        is_trouble=True)

            except Exception as e:
                self.j_mngr.log_events(f"Unable to report some completion information: model, usage.  Error: {e}",
                                    TroubleSgltn.Severity.INFO,
                                    True)    

        return CGPT_response
    

class claude_request(Request):

    def request_completion(self, **kwargs):
        claude_completion = ""
        return claude_completion

class dall_e_request(Request):

    def __init__(self):
        super().__init__()  # Ensures common setup from Request
        self.trbl = TroubleSgltn() 

    def request_completion(self, **kwargs)->tuple[torch.Tensor, str]:

        GPTmodel = kwargs.get('model')
        prompt = kwargs.get('prompt')
        image_size = kwargs.get('image_size')    
        image_quality = kwargs.get('image_quality')
        style = kwargs.get('style')
        batch_size = kwargs.get('batch_size', 1)

        self.trbl.set_process_header('Dall-e Request')

        batched_images = torch.zeros(1, 1024, 1024, 3, dtype=torch.float32)
        revised_prompt = "Image and mask could not be created"  # Default prompt message
        
        if not self.cFig.openaiClient:
            self.j_mngr.log_events("OpenAI API key is missing or invalid.  Key must be stored in an enviroment variable (see ReadMe).  This node is not functional.",
                                   TroubleSgltn.Severity.WARNING,
                                   True)
            return(batched_images, revised_prompt)
                
        client = self.cFig.openaiClient 
        
        
        self.j_mngr.log_events(f"Talking to Dalle model: {GPTmodel}",
                               is_trouble=True)

        have_rev_prompt = False   
        images_list = []

        for _ in range(batch_size):
            try:
                response = client.images.generate(
                    model = GPTmodel,
                    prompt = prompt, 
                    size = image_size,
                    quality = image_quality,
                    style = style,
                    n=1,
                    response_format = "b64_json",
                )
 
            # Get the revised_prompt
                if response and not 'error' in response:
                    if not have_rev_prompt:
                        revised_prompt = response.data[0].revised_prompt
                        have_rev_prompt = True
                    #Convert the b64 json to a pytorch tensor
                    b64Json = response.data[0].b64_json
                    if b64Json:
                        png_image, _ = self.dalle.b64_to_tensor(b64Json)
                        images_list.append(png_image)
                    else:
                        self.j_mngr.log_events(f"Dalle-e could not process an image in your batch of: {batch_size} ",
                                            TroubleSgltn.Severity.WARNING,
                                            True)  
                    
                else:
                    self.j_mngr.log_events(f"Dalle-e could not process an image in your batch of: {batch_size} ",
                                        TroubleSgltn.Severity.WARNING,
                                        True)   
            except openai.APIConnectionError as e: 
                self.j_mngr.log_events(f"ChatGPT server connection error in an image in your batch of {batch_size} Error: {e.__cause__}",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
            except openai.RateLimitError as e:
                self.j_mngr.log_events(f"ChatGPT RATE LIMIT error in an image in your batch of {batch_size} Error: {e}: {e.response}",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
                time.sleep(0.5)
            except openai.APIStatusError as e:
                self.j_mngr.log_events(f"ChatGPT STATUS error in an image in your batch of {batch_size}; Error: {e.status_code}:{e.response}",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
            except Exception as e:
                self.j_mngr.log_events(f"An unexpected error in an image in your batch of {batch_size}; Error:{e}",
                                        TroubleSgltn.Severity.ERROR,
                                        True)
                
                
        if images_list:
            count = len(images_list)
            self.j_mngr.log_events(f'{count} images were processed successfully in your batch of: {batch_size}',
                                   is_trouble=True)
            
            batched_images = torch.cat(images_list, dim=0)
        else:
            self.j_mngr.log_events(f'No images were processed in your batch of: {batch_size}',
                                   TroubleSgltn.Severity.WARNING,
                                   is_trouble=True)
        self.trbl.pop_header()
        return(batched_images, revised_prompt)

class request_context:
    def __init__(self)-> None:
        self._request = None
        self.j_mngr = json_manager()

    @property
    def request(self)-> Request:
        return self._request

    @request.setter
    def request(self, request:Request)-> None:
        self._request = request

    def execute_request(self, **kwargs):
        if self._request is not None:
            return self._request.request_completion(**kwargs)
        
        self.j_mngr.log_events("No request strategy object was set",
                               TroubleSgltn.Severity.ERROR,
                               True)
        return None
    
class request_utils:

    def __init__(self)-> None:
        self.j_mngr = json_manager()

    def build_data_multi(self, prompt:str, instruction:str="", examples:list=None, image:str=None):
        """
        Builds a list of message dicts, aggregating 'role:user' content into a list under 'content' key.
        - image: Base64-encoded string or None. If string, included as 'image_url' type content.
        - prompt: String to be included as 'text' type content under 'user' role.
        - examples: List of additional example dicts to be included.
        - instruction: Instruction string to be included under 'system' role.
        """
        messages = []
        user_role = {"role": "user", "content": None}
        user_content = []

        if examples is None:
            examples = []

        if image and isinstance(image,str):
            image_url = f"data:image/jpeg;base64,{image}"
            user_content.append({"type": "image_url", "image_url": {"url":image_url}})
        elif image:
            self.j_mngr.log_events("Image file is invalid.  Image will be disregarded in the generated output.",
                                TroubleSgltn.Severity.WARNING,
                                True)
        
        if prompt:
            user_content.append({"type": "text", "text": f"PROMPT: {prompt}"})


        user_role['content'] = user_content    

        messages.append(user_role)

        if examples:
            messages.extend(examples)

        if instruction:
            messages.append({"role": "system", "content": instruction})

        return messages
    
    def build_data_basic(self, prompt:str, examples:list=None, instruction:str=""):
        """
        Builds a list of message dicts, presenting each 'role:user' item in its own dict.
        - prompt: String to be included as 'text' type content under 'user' role.
        - examples: List of additional example dicts to be included.
        - instruction: Instruction string to be included under 'system' role.
        """

        messages = []

        if examples is None:
            examples = []
        
        if prompt:
            messages.append({"role": "user", "content": prompt})

        if examples:
            messages.extend(examples)

        if instruction:
            messages.append({"role": "system", "content": instruction})

        return messages
    
    def build_data_ooba(self, prompt:str, examples:list=None, instruction:str="")-> list:
        """
        Builds a list of message dicts, presenting each 'role:user' item in its own dict.
        Since Oobabooga's system message is broken it includes it in the prompt
        - prompt: String to be included as 'text' type content under 'user' role.
        - examples: List of additional example dicts to be included.
        - instruction: Instruction string to be included under 'system' role.
        """

        messages = []

        ooba_prompt =  f"INSTRUCTION: {instruction} \nPROMPT: {prompt}"

        if examples is None:
            examples = []
        
        if ooba_prompt:
            messages.append({"role": "user", "content": ooba_prompt})

        if examples:
            messages.extend(examples)

        return messages 
    
    
    def build_web_header(self, key:str=""):
        if key:
            headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}" 
            }
        else:
            headers = {
                "Content-Type": "application/json"
            }    

        return headers    

    def validate_and_correct_url(self, user_url:str, required_path:str='/v1/chat/completions'):
        """
        Takes the user's url and make sure it has the correct path for the connection
        args:
            user_url (str): The url to be validated and corrected if necessary
            required_path (str):  The correct path
        return:            
            A string with either the original url if it was correct or the corrected url if it wasn't
        """
        corrected_url = ""
        parsed_url = urlparse(user_url)
                
        # Check if the path is the required_path
        if not parsed_url.path == required_path:
            corrected_url = urlunparse((parsed_url.scheme,
                                        parsed_url.netloc,
                                        required_path,
                                        '',
                                        '',
                                        ''))

        else:
            corrected_url = user_url
            
        self.j_mngr.log_events(f"URL was validated and is being presented as: {corrected_url}",
                            TroubleSgltn.Severity.INFO,
                            True)

        return corrected_url   
    
    def clean_response_text(self, text: str)-> str:
        # Replace multiple newlines or carriage returns with a single one
        cleaned_text = re.sub(r'\n+', '\n', text).strip()
        return cleaned_text
    
    