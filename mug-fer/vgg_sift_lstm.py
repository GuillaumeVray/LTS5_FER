import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import pickle
from sklearn.cross_validation import StratifiedKFold
from sklearn.metrics import confusion_matrix

from keras.models import Model, Sequential, load_model
from keras.layers import Input, Convolution2D, ZeroPadding2D, MaxPooling2D, Flatten, Dense, Dropout, Activation, TimeDistributed, LSTM, BatchNormalization, GlobalAveragePooling2D
from keras.callbacks import Callback, EarlyStopping, ModelCheckpoint
from keras import optimizers

from extract import extract_frames, extract_data, extract_model_features
from training import create_vgg_fc7, train_crossval, CustomVerbose
from sift import extract_all_sift_features
from plot import plot_histories, plot_confusion_matrix
from const import *

def create_lstm_sift_model():
	"""Creates the LSTM model that goes on top of VGG and SIFT.
	"""
	lstm_units = 32
	hidden_units = 16
	input_dim = 10624  # 4096 for vgg + 6528 for sift

	input_shape = (nb_frames, input_dim)

	lstm = Sequential()
	lstm.add(LSTM(lstm_units, input_shape=input_shape))
	lstm.add(Dropout(0.5))
	lstm.add(Dense(hidden_units, activation="relu"))
	lstm.add(Dropout(0.5))
	lstm.add(Dense(nb_emotions, activation="softmax"))

	lstm.compile(loss='categorical_crossentropy',
				  optimizer=optimizers.SGD(),
				  metrics=['accuracy'])
	return lstm

###########################
######## MAIN CODE ########
###########################

# Train the model only if the call was made with argument 'train',
# otherwise, just test it
train = len(sys.argv) > 1 and sys.argv[1]=='train'

# If the sift or vgg features were pre-computed, we don't have to recompute them
load_vgg_features = os.path.isfile(vgg_features_path)
load_sift_features = os.path.isfile(sift_features_path)
load_frames = os.path.isdir(frames_path)


## EXTRACTION ##

# If not already done, we extract the relevant frames from the raw MUG dataset
if not load_frames:
	extract_frames(subjects_path, frames_path)


# Now we extract the training and target data from the frames
if not(load_sift_features and load_vgg_features):
	x, y = extract_data(frames_path)
else:
	with open(y_data_path, 'rb') as f:
		y = pickle.load(f)


if load_vgg_features:
	with open(vgg_features_path, 'rb') as f:
		vgg_features = pickle.load(f)
else:
	# Create VGG model
	vgg16_fc7 = create_vgg_fc7(vgg_weights_path)

	# Extract the VGG features
	vgg_features = extract_model_features(vgg16_fc7, x)


if load_sift_features:
	with open(sift_features_path, 'rb') as f:
		sift_features = pickle.load(f)
else:
	# Extract SIFT features
	sift_features = extract_all_sift_features(x)


# Concatenate the VGG features with the SIFT features
vgg_sift_features = np.concatenate([vgg_features, sift_features], axis=2)


## TRAINING ##

if train:
	print("Training LSTM model...")
	batch_size=32
	epochs=300
	n_folds=5
	save_best_model = False
	weights_path = 'models/vgg-sift-lstm2.h5'

	# Create the callbacks
	custom_verbose = CustomVerbose(epochs)
	early_stop = EarlyStopping(patience=50)
	model_checkpoint = ModelCheckpoint(weights_path,
												 monitor='val_acc',
												 save_best_only=True,
												 save_weights_only=True)
	callbacks = [custom_verbose, early_stop, model_checkpoint] if save_best_model else [custom_verbose, early_stop]

	lstm_sift, skf, histories = train_crossval(create_lstm_sift_model,
															vgg_sift_features,
															y,
															batch_size=batch_size,
															epochs=epochs,
															callbacks=callbacks,
															n_folds=n_folds,
															save_best_model=save_best_model,
															weights_path=weights_path)

	print("\nTraining complete.")
	plot_histories(histories, 'VGG-SIFT-LSTM, {}-fold cross-validation'.format(n_folds))

else:
	lstm_sift = load_model(vgg_sift_lstm_model_path)


## TESTING ##

# Get back the train/test split used
train_idx, test_idx = [],[]
labels = np.argmax(y, axis=1)
skf = StratifiedKFold(labels, n_folds=5, shuffle=False)
for i, (train, test) in enumerate(skf):
	train_idx.append(train)
	test_idx.append(test)

# Get emotion predictions
test_indices = test_idx[1]
y_predict = lstm_sift.predict_classes(vgg_sift_features[test_indices])
y_true = np.argmax(y[test_indices], axis=1)

# Computes the accuracy
acc = (y_predict==y_true).sum()/len(y_predict)
print('Test accuracy : {:.4f}'.format(acc))

# Plot the confusion matrix
cm = confusion_matrix(np.argmax(y[test_indices], axis=1), y_predict)
plot_confusion_matrix(cm, emotions, title='VGG-SIFT-LSTM', normalize=True)

