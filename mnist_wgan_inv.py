import sys, os
os.environ["CUDA_VISIBLE_DEVICES"]="6"
import numpy as np
import PIL
import time
from IPython import display
import imageio
import glob
import tensorflow as tf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.switch_backend('agg')
from tqdm import tqdm
import data_loader

"""### Import TensorFlow and enable eager execution"""

print(tf.__version__)

"""### Start Tensorboard Logging
"""
train_log_dir = 'summaries/mnist_gan/train'
test_log_dir = 'summaries/mnist_gan/test'
train_summary_writer = tf.summary.create_file_writer(train_log_dir)
test_summary_writer = tf.summary.create_file_writer(test_log_dir)

"""### Load the dataset
We are going to use the MNIST dataset to train the generator and the discriminator. The generator will generate handwritten digits resembling the MNIST data.
"""


# (train_images, train_labels), (_, _) = tf.keras.datasets.mnist.load_data()
dataset = data_loader.load_data()
# print(train_images[0])


BATCH_SIZE = 1024
NUM_UPDATES_PER_BATCH = 4

OUTPUT_SIZE = 128
# The size of the z space - the input space to the generator
Z_DIM = 128
# The size of the latent space in all 3 models in the GAN
LATENT_DIM = 64

DIVERGENCE_LAMBDA = 0.1
GRAD_PENALTY_FACTOR = 10.0

"""### Use tf.data to create batches and shuffle the dataset"""

num_test_images = 8
test_dataset = dataset.take(num_test_images).cache()
train_dataset = dataset.skip(num_test_images).batch(BATCH_SIZE)

"""## Create the models
We will use tf.keras [Sequential API](https://www.tensorflow.org/guide/keras#sequential_model) to define the generator and discriminator models.
### The Generator Model
The generator is responsible for creating convincing images that are good enough to fool the discriminator. The network architecture for the generator consists of [Conv2DTranspose](https://www.tensorflow.org/api_docs/python/tf/keras/layers/Conv2DTranspose) (Upsampling) layers. We start with a fully connected layer and upsample the image two times in order to reach the desired image size of 28x28x1. We increase the width and height, and reduce the depth as we move through the layers in the network. We use [Leaky ReLU](https://www.tensorflow.org/api_docs/python/tf/keras/layers/LeakyReLU) activation for each layer except for the last one where we use a tanh activation.
"""


def make_generator_model():
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Dense(LATENT_DIM * 8*4*4*2*3, use_bias=False, input_shape=(Z_DIM,), name='Generator_Input'))
    model.add(tf.keras.layers.BatchNormalization())
    model.add(tf.keras.layers.ReLU())

    model.add(tf.keras.layers.Reshape((4, 4, LATENT_DIM*8*2*3)))
    print("Model shape should be (None, 4, 4, 1024*3) -", model.output_shape)
    assert model.output_shape == (None, 4, 4, 1024*3)

    model.add(tf.keras.layers.Conv2DTranspose(
        LATENT_DIM * 4*3, (5, 5), strides=(2, 2), padding='same', use_bias=False, name='Generator_1'))
    model.add(tf.keras.layers.BatchNormalization())
    model.add(tf.keras.layers.ReLU())
    print("Model shape should be (None, 8, 8, 256*3) -", model.output_shape)
    assert model.output_shape == (None, 8, 8, 256*3)

    #model.add(tf.keras.layers.Conv2DTranspose(
    #    64, (4, 4), strides=(2, 2), padding='same', use_bias=False))
    model.add(tf.keras.layers.Conv2DTranspose(8*3, (9, 9), strides=(4, 4),
        padding='same', use_bias=False, activation='tanh', name='Generator_2'))
    print("Model shape should be (None, 32, 32, 8*3) -", model.output_shape)
    assert model.output_shape == (None, 32, 32, 8*3)
    #model.add(tf.keras.layers.BatchNormalization())
    #model.add(tf.keras.layers.LeakyReLU())

    model.add(tf.keras.layers.Conv2DTranspose(3, (9, 9), strides=(4, 4),
        padding='same', use_bias=False, activation='tanh', name='Generator_3'))
    print("Model shape should be (None, 128, 128, 3) -", model.output_shape)
    assert model.output_shape == (None, 128, 128, 3)

    model.summary()
    return model


"""### The Discriminator model
The discriminator is responsible for distinguishing fake images from real images. It's similar to a regular CNN-based image classifier.
"""

def make_discriminator_model():
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM, (5, 5), strides=(2, 2), padding='same', input_shape=(128, 128, 3), name='Discriminator_Input'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))

    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM*2, (5, 5), strides=(2, 2), padding='same', name='Discriminator_1'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))

    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM*4, (5, 5), strides=(2, 2), padding='same', name='Discriminator_2'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))

    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(1, name='Discriminator_3'))
    model.summary()
    return model

def make_inverter_model():
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM, (5, 5), strides=(2, 2), padding='same', input_shape=(128, 128, 3), name='Inverter_Input'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))
    print("Model shape should be (None, 64, 64, 64) -", model.output_shape)
    assert model.output_shape == (None, 64, 64, 64)

    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM*2, (5, 5), strides=(2, 2), padding='same', name='Inverter_1'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))
    print("Model shape should be (None, 32, 32, 128) -", model.output_shape)
    assert model.output_shape == (None, 32, 32, 128)

    model.add(tf.keras.layers.Conv2D(
        LATENT_DIM*4, (5, 5), strides=(2, 2), padding='same', name='Inverter_2'))
    model.add(tf.keras.layers.LeakyReLU())
    #model.add(tf.keras.layers.Dropout(0.3))
    print("Model shape should be (None, 16, 16, 256) -", model.output_shape)
    assert model.output_shape == (None, 16, 16, 256)

    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(LATENT_DIM * 8, name='Inverter_3'))
    model.add(tf.keras.layers.Dense(Z_DIM, name='Inverter_4'))

    model.summary()
    return model

generator = make_generator_model()
discriminator = make_discriminator_model()
inverter = make_inverter_model()

"""## Define the loss functions and the optimizer
Let's define the loss functions and the optimizers for the generator and the discriminator.
### Generator loss
The generator loss is a sigmoid cross entropy loss of the generated images and an array of ones, since the generator is trying to generate fake images that resemble the real images.
"""
@tf.function
def generator_loss(generated_output, gradient_penalty):
    return tf.compat.v1.losses.sigmoid_cross_entropy(tf.ones_like(generated_output), generated_output) + gradient_penalty

"""### Discriminator loss
The discriminator loss function takes two inputs: real images, and generated images. Here is how to calculate the discriminator loss:
1. Calculate real_loss which is a sigmoid cross entropy loss of the real images and an array of ones (since these are the real images).
2. Calculate generated_loss which is a sigmoid cross entropy loss of the generated images and an array of zeros (since these are the fake images).
3. Calculate the total_loss as the sum of real_loss and generated_loss.
"""
@tf.function
def discriminator_loss(real_output, generated_output):
    # [1,1,...,1] with real output since it is true and we want our generated examples to look like it
    real_loss = tf.compat.v1.losses.sigmoid_cross_entropy(
        multi_class_labels=tf.ones_like(real_output), logits=real_output)

    # [0,0,...,0] with generated images since they are fake
    generated_loss = tf.compat.v1.losses.sigmoid_cross_entropy(
        multi_class_labels=tf.zeros_like(generated_output), logits=generated_output)

    total_loss = real_loss + generated_loss

    return total_loss

"""### Inverter Loss
The inverter loss takes four inputs: noise z, invert(generate(z)), image x, and generate(invert(x)).
"""
@tf.function
def inverter_loss(real_noise, rec_noise, real_image, rec_image):
    divergence = DIVERGENCE_LAMBDA * tf.reduce_mean(tf.square(real_noise - rec_noise))
    reconstruction_err = tf.reduce_mean(tf.square(real_image - rec_image))

    return divergence + reconstruction_err

"""The discriminator and the generator optimizers are different since we will train two networks separately."""

generator_optimizer = tf.compat.v1.train.AdamOptimizer(1e-4)
discriminator_optimizer = tf.compat.v1.train.AdamOptimizer(1e-4)
inverter_optimizer = tf.compat.v1.train.AdamOptimizer(1e-4)

"""**Checkpoints (Object-based saving)**"""

checkpoint_dir = './training_checkpoints_wgan'
#checkpoint_prefix = os.path.join(checkpoint_dir, "ckpt")
checkpoint = tf.train.Checkpoint(generator_optimizer=generator_optimizer,
                                 discriminator_optimizer=discriminator_optimizer,
                                 inverter_optimizer=inverter_optimizer,
                                 generator=generator,
                                 discriminator=discriminator,
                                 inverter=inverter)
manager = tf.train.CheckpointManager(
    checkpoint, directory=checkpoint_dir, max_to_keep=2)

"""## Set up GANs for Training
Now it's time to put together the generator and discriminator to set up the Generative Adversarial Networks, as you see in the diagam at the beginning of the tutorial.
**Define training parameters**
"""

EPOCHS = 50
num_examples_to_generate = 16

# We'll re-use this random vector used to seed the generator so
# it will be easier to see the improvement over time.
random_vector_for_generation = tf.random.normal([num_examples_to_generate,
                                                 Z_DIM])

"""**Define training method**
We start by iterating over the dataset. The generator is given a random vector as an input which is processed to  output an image looking like a handwritten digit. The discriminator is then shown the real MNIST images as well as the generated images.
Next, we calculate the generator and the discriminator loss. Then, we calculate the gradients of loss with respect to both the generator and the discriminator variables.
"""

@tf.function
def train_step(images, epoch):
    #print("Train step %d" % epoch)
    if images.shape[0] != BATCH_SIZE:
        print("training images were not full batch, was " + str(images.shape[0]))
        return
   # generating noise from a normal distribution
    noise = tf.random.normal([BATCH_SIZE, Z_DIM])

    with tf.GradientTape() as gen_tape, tf.GradientTape() as disc_tape, tf.GradientTape() as gp_tape, tf.GradientTape() as inv_tape:
        generated_images = generator(noise, training=True)

        real_output = discriminator(images, training=True)
        generated_output = discriminator(generated_images, training=True)

        rec_image = generator(inverter(images))
        rec_noise = inverter(generator(noise))

        # Calculate WGAN gradient penalty
        alpha = tf.random.uniform(shape=[BATCH_SIZE, 1], minval=0., maxval=1.)
        x_p = tf.reshape(generated_images, [-1, 128*128*3])
        x = tf.reshape(images, [-1, 128*128*3])
        difference = x_p - x
        interpolate = tf.reshape(x + alpha * difference, [-1, 128, 128, 3])
        gradient = gp_tape.gradient(discriminator(interpolate), [interpolate])[0]
        slope = tf.sqrt(tf.reduce_sum(tf.square(gradient), axis=1))
        gradient_penalty = GRAD_PENALTY_FACTOR * tf.reduce_mean((slope - 1.) ** 2)

        gen_loss = generator_loss(generated_output, gradient_penalty)
        disc_loss = discriminator_loss(real_output, generated_output)
        inv_loss = inverter_loss(noise, rec_noise, images, rec_image)

        with train_summary_writer.as_default():
            tf.summary.scalar('gen_loss', gen_loss, step=epoch)
            tf.summary.scalar('disc_loss', disc_loss, step=epoch)
            tf.summary.scalar('inv_loss', inv_loss, step=epoch)

    gradients_of_generator = gen_tape.gradient(gen_loss, generator.variables)
    gradients_of_discriminator = disc_tape.gradient(
        disc_loss, discriminator.variables)
    gradients_of_inverter = inv_tape.gradient(inv_loss, inverter.variables)

    generator_optimizer.apply_gradients(
        zip(gradients_of_generator, generator.variables))
    discriminator_optimizer.apply_gradients(
        zip(gradients_of_discriminator, discriminator.variables))
    inverter_optimizer.apply_gradients(
        zip(gradients_of_inverter, inverter.variables))


"""This model takes about ~30 seconds per epoch to train on a single Tesla K80 on Colab, as of October 2018.
Eager execution can be slower than executing the equivalent graph as it can't benefit from whole-program optimizations on the graph, and also incurs overheads of interpreting Python code. By using [tf.contrib.eager.defun](https://www.tensorflow.org/api_docs/python/tf/contrib/eager/defun) to create graph functions, we get a ~20 secs/epoch performance boost (from ~50 secs/epoch down to ~30 secs/epoch). This way we get the best of both eager execution (easier for debugging) and graph mode (better performance).
"""
def train(dataset, epochs):
    generate_and_save_images(generator, 1, random_vector_for_generation)
    print("Training")
    for epoch in range(epochs):
        start = time.time()
        print("Training {} iterations in epoch {}".format(130000/BATCH_SIZE, epoch))
        for current_step, img_and_labels in tqdm(enumerate(dataset)):
            images = img_and_labels[0]
            for i in range(NUM_UPDATES_PER_BATCH):
                train_step(images, current_step)
            if current_step % 4 == 0:
                print("Saving checkpoint...")
                manager.save()
                generate_and_save_images(generator,
                                         epoch + 1,
                                         random_vector_for_generation)
                reconstruct_and_save_images(generator, inverter, epoch+1, test_dataset)
        display.clear_output(wait=True)

        # saving (checkpoint) the model every n epochs
        #if (epoch + 1) % 4 == 0:
        print("Saving checkpoint and models...")
        manager.save()
        generator.save('models/generator.h5')
        inverter.save('models/inverter.h5')
        generate_and_save_images(generator,
                                 epoch + 1,
                                 random_vector_for_generation)
        reconstruct_and_save_images(generator, inverter, epoch+1, test_dataset)

        print('Time taken for epoch {} is {} sec'.format(epoch + 1,
                                                         time.time()-start))
    # generating after the final epoch
    display.clear_output(wait=True)
    generate_and_save_images(generator,
                             epochs,
                             random_vector_for_generation)
    reconstruct_and_save_images(generator, inverter, epochs, test_dataset)
    print("Saving models!")
    generator.save('models/generator.h5')
    inverter.save('models/inverter.h5')


"""**Generate and save images**"""
def generate_and_save_images(model, epoch, test_input):
    # make sure the training parameter is set to False because we
    # don't want to train the batchnorm layer when doing inference.
    predictions = model(test_input, training=False)

    fig = plt.figure(figsize=(8, 8))

    for i in range(predictions.shape[0]):
        plt.subplot(4, 4, i+1)
        predi = convert_array_to_image(predictions[i])
        plt.imshow(predi)
        plt.axis('off')

    plt.savefig("images/" + 'sample_at_epoch_{:04d}.png'.format(epoch))
    plt.close(fig)
    plt.clf()

def reconstruct_and_save_images(generator, inverter, epoch, test_images):
    test_images = [tf.reshape(image_and_label[0], [1, 128, 128, 3]) for image_and_label in test_images]
    predictions = generator(inverter(test_images, training=False), training=False)


    fig = plt.figure(figsize=(8, 8))

    for i in range(predictions.shape[0]):
        plt.subplot(4, 4, 2*i+1)
        predi = convert_array_to_image(test_images[i])
        plt.imshow(predi)
        plt.axis('off')
        plt.subplot(4, 4, 2*i+2)
        predi = convert_array_to_image(predictions[i])
        plt.imshow(predi)
        plt.axis('off')

    plt.savefig("images/" + 'reconstruction_at_epoch_{:04d}.png'.format(epoch))
    #plt.show()
    plt.clf()
    plt.close(fig)

def convert_array_to_image(array):
    array = tf.reshape(array, [128, 128, 3])
    """Converts a numpy array to a PIL Image and undoes any rescaling."""
    img = PIL.Image.fromarray(np.uint8((array + 1.0) / 2.0 * 255), mode='RGB')
    return img

"""## Train the GANs
We will call the train() method defined above to train the generator and discriminator simultaneously. Note, training GANs can be tricky. It's important that the generator and discriminator do not overpower each other (e.g., that they train at a similar rate).
At the beginning of the training, the generated images look like random noise. As training progresses, you can see the generated digits look increasingly real. After 50 epochs, they look very much like the MNIST digits.
**Restore the latest checkpoint**
"""

if __name__ == "__main__":
    # restoring the latest checkpoint in checkpoint_dir
    #if not tf.train.latest_checkpoint(checkpoint_dir) is None:
    print("Current process PID: " + str(os.getpid()))
    print("Restoring from", manager.latest_checkpoint)
    checkpoint.restore(manager.latest_checkpoint)
        #checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))

    generator.save('models/generator.h5')
    inverter.save('models/inverter.h5')
    # save the architecture string to a file somehow, the below will work
    with open('models/generator_arch.json', 'w') as arch_file:
        arch_file.write(generator.to_json())
    with open('models/inverter_arch.json', 'w') as arch_file:
        arch_file.write(inverter.to_json())

    print("Num epochs", EPOCHS)
    train(train_dataset, EPOCHS)
