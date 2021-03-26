### IMPORTS ###
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from PIL import Image
from skimage.segmentation import felzenszwalb, slic, quickshift
from sklearn.metrics import pairwise_distances
from sklearn.linear_model import Ridge
from torchvision import transforms
import numpy as np 
import torch
import torch.nn.functional as F

### IMAGE ### 
class ImageObject():
    
    def __init__(self, original_image):
        """Initialize image object
        
        Inputs:
            original_image: any object that can be turned into a numpy array of shape (W,H) or (W,H,C)
        """
        #keep image as numpy array
        if type(original_image) == np.ndarray:
            self.original_image = original_image
        else:
            self.original_image = np.array(original_image)

        self.masked_image = None
        self.superpixels = None
        self.shape = self.original_image.shape

    def show(self):
        """Display original image"""
        plt.imshow(self.original_image)


### EXPLAINER ###
class Explainer():

    def __init__(self, classifier, segmentation_method, kernel_method, preprocess_function = None, device = None):
        """
        Initialize LIME Explainer

        Inputs:
            classifier: pytorch image classifier model. Should output logits.
            segmentation_method: SegmentationMethod
            kernel_method: KernelMethod
            preprocess_function: Preprocess function that transforms data to be the same as during
                                 blackbox classifier training. If no normalization was used, don't 
                                 use this option.
            device: pytorch device to use, default is cuda if available else cpu.
        """
        self.segmentation_method = segmentation_method
        self.kernel_method = kernel_method
        if preprocess_function is None:
            self.preprocess_function = transforms.Compose([transforms.ToTensor()])
        else:
            self.preprocess_function = preprocess_function
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device
        self.classifier = classifier.to(self.device)

    def segment_image(self, image):
        """
        Segment image pixels into superpixels

        Inputs:
            image: ImageObject
        """
        image.superpixels = self.segmentation_method(image.original_image)        

    def mask_image(self, image, mask_value = None):
        """
        Generate mask for pixels in image.
        
        Inputs:
            image: ImageObject
            mask_value: If mask_value = None, then each masked pixel is the average
                        of the superpixel it belongs to. Else, every pixel is set to
                        mask_value
        """

        img = image.original_image #get original image
        masked_img = img.copy() #copy original image
        superpixels = image.superpixels #get original superpixels
        superpixel_ids = np.unique(superpixels) #get superpixels identifiers

        #set masked image pixels to average of corresponding superpixel
        if mask_value is None:
            for x in superpixel_ids:
                masked_img[superpixels == x] = np.mean(img[superpixels == x], axis=0)
        #set masked image pixels to mask_value
        else:
            masked_img[:] = mask_value

        image.masked_image = masked_img 

    def sample_superpixels(self, image, num_samples):
        """
        Samples different configurations of turned on superpixels for the image.
        
        Inputs:
            image: ImageObject
            num_samples: number of different superpixel configurations to sample

        Outputs:
            superpixel_samples: numpy array of shape (num_samples, num_superpixels).
                                Superpixels on/off indicator for each sample.
            sampled_images: list of numpy arrays.
                            Sampled image with superpixels randomly tuned on/off. 
        """
        # sample num_samples collections of superpixels
        num_superpixels = np.unique(image.superpixels).size
        superpixel_samples = np.random.randint(2, size=(num_samples, num_superpixels))

        # apply samples to fudged image to generate pertubed images
        sampled_images = list()
        for sample in superpixel_samples:
            sample_masked_image = image.original_image.copy()
            turned_on_superpixels = np.where(sample == 1)[0]
            mask = np.zeros(image.superpixels.shape).astype(bool)
            for superpixel in turned_on_superpixels:  # turn on the sampled pixels
                mask[image.superpixels == superpixel] = True
            sample_masked_image[mask] = image.masked_image[mask]
            sampled_images.append(sample_masked_image)
        return superpixel_samples, sampled_images

    def map_blaxbox_io(self, sampled_images):    
        """
        Map samples to predicted labels/categories using blackbox classifier

        Inputs:
            sampled_images: Image samples resulting from different superpixel combinations.
                            List of numpy arrays (rows, col, 3). 

        Outputs:
            sample_labels: Numpy array of shape (num_samples, num_labels). Predicted labels for each sample.
        """
        sample_labels = list()
        self.classifier.eval()
        with torch.no_grad():
            for sample_image in sampled_images:
                sample_image = torch.unsqueeze(self.preprocess_function(sample_image), dim=0).to(self.device)
                out = self.classifier(sample_image)
                softmax_out = F.softmax(out, dim = 1)
                labels = torch.squeeze(softmax_out, dim = 0).detach().cpu().numpy()
                sample_labels.append(labels)
        sample_labels = np.asarray(sample_labels)

        return sample_labels

    def get_distances(self, superpixel_samples):
        """
        Computes the pairwise distance to the original image superpixel configuration and sampled ones.

        Inputs:
            superpixel_samples: the list of samples of superpixel configurations

        Outputs:
            distances: 1D numpy array. Distances from superpixel samples to original image
        """
        # make an array of ones (i.e. all superpixels on)
        no_mask_array = np.ones(superpixel_samples.shape[1]).reshape(1, -1)
        # distances from each sample to original
        distances = pairwise_distances(superpixel_samples, no_mask_array, metric="cosine")
        return distances.flatten()

    def weigh_samples(self, distances):
        """
        Weigh samples using kernel function on sample distances from original image

        Inputs:
            distances: 1D numpy array. Distances from superpixel samples to original image

        Outputs:
            sample_weights: 1D numpy array. Sample distances weighed by kernel method.
        """
        sample_weights = self.kernel_method(distances)
        return sample_weights

    def select_features(self):
        """
        Superpixel selection to reduce complexity of explanation.
        """
        pass

    def fit_LLR(self, samples, weights, labels, regressor = None):
        """
        Fits and returns a regression model to the superpixel samples and the classifier outputs.

        Input:
            samples: numpy array of shape (num_samples, num_superpixels).
                     Superpixels on/off indicator for each sample.
            weights: 1D numpy array. Sample distances weighed by kernel method.
            labels: Numpy array of shape (num_samples, num_labels). Predicted labels for each sample.
            regressor: Linear regressor to use, default is ridge regression.
        
        Outputs:
            model: Local linear regression model fitted to image.
        """
        if regressor is None:
            model = Ridge()
        else:
            model = regressor
        model.fit(samples, labels, sample_weight=weights)
        return model

    def explain_image(self, image, num_samples, top_labels = None, mask_value = None, regressor = None):
        """
        Explain image using superpixels.

        Inputs:
            image: ImageObject
            num_samples: Number of samples to use for local linear regression of image
            top_labels: Number of labels/categories from classifier to include in explanation.
                        Labels are picked from highest to lowest predicted for the image. Default is all labels.
            mask_value: If mask_value = None, then each masked pixel is the average
                        of the superpixel it belongs to. Else, every pixel is set to
                        mask_value
            regressor: Linear regressor to use, default is ridge regression.

        Outputs:
            explanation
        """
        if image.superpixels is None:
            self.segment_image(image, num_samples)
        if image.masked_image is None: # What if mask_value changes?
            self.mask_image(image, mask_value)

        superpixel_samples, sampled_images = self.sample_superpixels(image, num_samples)
        distances = self.get_distances(superpixel_samples)
        sample_weights = self.weigh_samples(distances)
        sample_labels = self.map_blaxbox_io(sampled_images)

        # select_features()

        if top_labels is None:
            labels = np.arange(sample_labels.shape[1])
        else:
            original_labels = self.map_blaxbox_io((image.original_image,))
            labels = np.flip(np.argsort(original_labels[0])[-top_labels:])

        LLR_model = self.fit_LLR(superpixel_samples, sample_weights, sample_labels, regressor)

        # create_explanation()

        return LLR_model


### SEGMENTATION ###
class SegmentationMethod():

    def __init__(self, method="quickshift", **method_args):
        """
        Set image segmentation method as a predefined algorithm or custom function

        Inputs:
            method: Either a string specifying one of predefined segmentaion algorithms:
                    "quickshift", "felzenszwalb", "slic",
                    Or a custom segmentation function.
            method_args: Any extra arguments needed by the chosen method.
        """
        self.method = method
        self.method_args = method_args

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
                
    def __call__(self, img):
        """
        Run segmentation method on image
        """
        return self.segmentation_method(img, **self.method_args)


### SIMILARITY KERNEL ###
class KernelMethod():

    def __init__(self, method="exponential", **method_args):
        """
        Set similarity kernel method as a predefined algorithm or custom function

        Inputs:
            method: Either a string specifying one of predefined segmentaion algorithms:
                    "exponential",
                    Or a custom kernel function.
            method_args: Any extra arguments needed by the chosen method.
        """
        self.method = method
        self.method_args = method_args

        if self.method == "exponential":
            self.kernel_method = lambda distances, kernel_width: np.sqrt(np.exp(-(distances ** 2) / kernel_width ** 2))
        elif isinstance(method, str):
            raise KeyError(f"Unknown kernel algorithm: {method}")
        else:
            self.kernel_method = method

    def __call__(self, distances):
        """
        Run kernel method on distances
        """
        return self.kernel_method(distances, **self.method_args)
