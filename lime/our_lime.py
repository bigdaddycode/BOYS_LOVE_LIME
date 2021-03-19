### IMPORTS ###
import numpy as np
import matplotlib.pyplot as plt

from pathlib import Path
from PIL import Image
from skimage.segmentation import felzenszwalb, slic, quickshift
import numpy as np 

### IMAGE ### 
class ImageObject():
    
    def __init__(self, original_image):
        """Initialize image object"""
        
        #keep image as numpy array
        if type(original_image) == np.ndarray:
            self.original_image = original_image
        else:
            self.original_image = np.array(original_image)
        
        self.masked_image = None
        self.superpixels = None
        self.shape = np.array(original_image).shape

    def show(self):
        """Display original image"""
        img = self.original_image
        plt.imshow(img)


### EXPLAINER ###
class Explainer():

    def __init__(self, segmentation_method, num_samples=1000):
        self.segmentation_method = segmentation_method
        self.num_samples = num_samples
    
    def segment_image(self, image, **kwargs):
        """
        image: ImageObject
        """
        image.superpixels = self.segmentation_method(image.original_image, **kwargs)        
        
    def mask_image(self, image, mask_value = None):
        """
        Generate mask for pixels in image.
        image: ImageObject
        mask_value: If mask_value = None, then each masked pixel is the average
                    of the superpixel it belongs to. Else, every pixel is set to
                    mask_value
        """
        
        img = image.original_image #get original image
        masked_img = img #copy original image
        superpixels = image.superpixels #get original superpixels
        superpixel_ids = np.unique(superpixels) #get superpixels identifiers
        
        #set masked image pixels to average of corresponding superpixel
        if mask_value == None:
            for x in superpixel_ids:
                masked_img[superpixels == x] = np.mean(img[superpixels == x], axis=0)
        #set masked image pixels to mask_value
        else:
            masked_img[:] = mask_value
        
        image.masked_image = masked_img 

    def sample_superpixels(self, image, num_samples):
        # sample num_samples collections of superpixels
        num_superpixels = np.unique(image.superpixels).size
        superpixel_samples = np.random.randint(2, size=(num_samples, num_superpixels))

        # apply samlpes to fudged image to generate pertubed images
        sampled_images = list()
        for sample in superpixel_samples:
            sample_masked_image = image.original_image.copy()
            turned_on_superpixels = np.where(sample == 1)[0]
            mask = np.zeros(image.superpixels.shape).astype(bool)
            for superpixel in turned_on_superpixels:  # turn on the sampled pixels
                mask[img.superpixels == superpixel] = True
            sample_masked_image[mask] = image.masked_image[mask]
            sampled_images.append(sample_masked_image)
        return sampled_images
    
        
### SEGMENTATION ###
class SegmentationMethod():

    def __init__(self, method="quickshift"):
        """
        Set image segmentation method as a predefined algorithm or custom function
        """
        self.method = method        
        if self.method == "quickshift":
            self.segmentation_method = quickshift
        elif self.method == "felzenszwalb":
            self.segmentation_method = felzenszwalb
        elif self.method == "slic":
            self.segmentation_method = slic
        elif isinstance(method, str):
            raise KeyError(f"Unknown segmentation algorithm: {method}")
        else:
            self.segmentation_method = method
                
    def __call__(self, img, **kwargs):
        """
        Run segmentation method on image
        """
        return self.segmentation_method(img, **kwargs)